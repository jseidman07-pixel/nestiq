"""
Nestiq Lease DNA Scanner
Uses Gemini 2.5 Pro multimodal capabilities to analyze student lease PDFs.
Extracts hidden clauses, red flags, and compares to Auburn market standards.
"""

import os
import base64
import json
from typing import Any
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai
from google.genai import types

load_dotenv()

# ── Clients ─────────────────────────────────────────────────────────────────
_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db    = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
_genai = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

# Auburn market standards for comparison
AUBURN_MARKET_STANDARDS = {
    "notice_to_vacate_days": 30,
    "early_termination_fee_months": 2,
    "security_deposit_max_months": 1,
    "guest_policy_max_days": 7,
    "pet_deposit_max": 300,
    "subletting": "typically allowed with approval",
    "maintenance_response_days": 3,
    "rent_increase_notice_days": 30,
}

LEASE_ANALYSIS_PROMPT = """
You are a legal document analyzer specializing in student housing leases in Auburn, Alabama.

Analyze this lease document thoroughly and extract the following information in JSON format.
Be extremely precise — pull exact clause numbers and page numbers when possible.

Return ONLY valid JSON with this exact structure:
{
  "property_name": "name if found or Unknown",
  "landlord_name": "landlord/property management name if found",
  "monthly_rent": 0,
  "lease_start": "date or Unknown",
  "lease_end": "date or Unknown",
  "lease_months": 0,
  "security_deposit": 0,
  "pet_deposit": 0,
  "pet_monthly_fee": 0,
  "notice_to_vacate_days": 0,
  "early_termination_fee": "exact description of penalty",
  "early_termination_amount": 0,
  "auto_renewal": true or false,
  "auto_renewal_notice_days": 0,
  "subletting_allowed": true or false,
  "subletting_conditions": "description or Not mentioned",
  "guest_policy_max_days": 0,
  "maintenance_responsibility": "tenant or landlord or shared - describe",
  "rent_increase_allowed": true or false,
  "rent_increase_notice_days": 0,
  "utilities_tenant_pays": ["list of utilities tenant pays"],
  "utilities_landlord_pays": ["list of utilities landlord pays"],
  "red_flags": [
    {
      "severity": "HIGH or MEDIUM or LOW",
      "clause": "clause number or section name",
      "issue": "one sentence description of the problem",
      "exact_language": "quote the exact problematic language from the lease",
      "vs_market": "how this compares to Auburn market standard"
    }
  ],
  "green_flags": [
    {
      "clause": "clause number or section",
      "benefit": "one sentence description of tenant-favorable term"
    }
  ],
  "unusual_clauses": [
    {
      "clause": "clause reference",
      "description": "description of unusual or noteworthy clause"
    }
  ],
  "overall_risk": "LOW or MEDIUM or HIGH",
  "risk_summary": "2-3 sentence plain English summary of the biggest risks",
  "negotiation_opportunities": ["list of specific things to negotiate"],
  "questions_to_ask": ["list of clarifying questions to ask landlord"]
}

Focus especially on:
1. Auto-renewal clauses that could trap students for another year
2. Early termination penalties beyond 2 months rent
3. Maintenance responsibilities shifted to tenant (especially HVAC, appliances)
4. Guest policies that restrict having friends stay over
5. Subletting bans that could strand students who need to leave
6. Notice-to-vacate requirements longer than 30 days
7. Vague language about deposit deductions
8. Rent increase clauses with little notice
9. Liability clauses that expose students to excessive risk
10. Any clause that restricts normal student activities

Be thorough but practical. This student needs to understand what they're signing.
"""


def analyze_lease_pdf(
    pdf_base64: str,
    filename: str = "lease.pdf",
) -> dict[str, Any]:
    """
    Analyze a lease PDF using Gemini multimodal capabilities.
    Extracts red flags, unusual clauses, and compares to Auburn market standards.

    Args:
        pdf_base64: Base64-encoded PDF content
        filename: Original filename for reference

    Returns:
        Complete lease analysis with red flags, risk score, and recommendations
    """
    try:
        print(f"Analyzing lease document: {filename}")

        # Decode PDF
        pdf_bytes = base64.b64decode(pdf_base64)

        # Call Gemini with the PDF
        response = _genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=pdf_bytes,
                    mime_type="application/pdf",
                ),
                types.Part.from_text(text=LEASE_ANALYSIS_PROMPT),
            ],
        )

        # Parse the JSON response
        raw_text = response.text.strip()

        # Strip markdown code blocks if present
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            raw_text = "\n".join(lines[1:-1])

        analysis = json.loads(raw_text)

        # Add metadata
        analysis["filename"] = filename
        analysis["analyzed_at"] = datetime.utcnow().isoformat()

        # Add market comparisons
        market_insights = _add_market_comparisons(analysis)
        analysis["market_insights"] = market_insights

        # Calculate risk score (0-100, higher = more risky)
        risk_score = _calculate_risk_score(analysis)
        analysis["risk_score"] = risk_score

        # Save to MongoDB for history
        _save_lease_analysis(analysis)

        return {
            "success": True,
            "analysis": analysis,
            "red_flag_count": len(analysis.get("red_flags", [])),
            "high_risk_count": len([f for f in analysis.get("red_flags", []) if f.get("severity") == "HIGH"]),
            "overall_risk": analysis.get("overall_risk", "UNKNOWN"),
            "risk_score": risk_score,
        }

    except json.JSONDecodeError as e:
        # Try to extract partial analysis
        return {
            "success": False,
            "error": f"Could not parse Gemini response as JSON: {str(e)}",
            "raw_response": response.text[:500] if "response" in dir() else "No response",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def _add_market_comparisons(analysis: dict) -> list[dict]:
    """Compare extracted lease terms to Auburn market standards."""
    insights = []

    notice = analysis.get("notice_to_vacate_days", 0)
    if notice > AUBURN_MARKET_STANDARDS["notice_to_vacate_days"]:
        insights.append({
            "field": "Notice to Vacate",
            "your_lease": f"{notice} days",
            "market_standard": f"{AUBURN_MARKET_STANDARDS['notice_to_vacate_days']} days",
            "assessment": "UNFAVORABLE",
            "note": f"Your lease requires {notice - AUBURN_MARKET_STANDARDS['notice_to_vacate_days']} more days notice than typical Auburn leases."
        })
    elif notice > 0:
        insights.append({
            "field": "Notice to Vacate",
            "your_lease": f"{notice} days",
            "market_standard": f"{AUBURN_MARKET_STANDARDS['notice_to_vacate_days']} days",
            "assessment": "STANDARD",
            "note": "Standard notice period for Auburn."
        })

    if analysis.get("auto_renewal"):
        insights.append({
            "field": "Auto-Renewal",
            "your_lease": f"Yes — {analysis.get('auto_renewal_notice_days', 0)} days notice to opt out",
            "market_standard": "Usually requires written notice to opt out",
            "assessment": "WATCH OUT",
            "note": "Auto-renewal can trap you for another full year if you miss the opt-out window."
        })

    if not analysis.get("subletting_allowed", True):
        insights.append({
            "field": "Subletting",
            "your_lease": "Not allowed",
            "market_standard": AUBURN_MARKET_STANDARDS["subletting"],
            "assessment": "UNFAVORABLE",
            "note": "No subletting means you're stuck paying rent even if you need to leave Auburn."
        })

    return insights


def _calculate_risk_score(analysis: dict) -> int:
    """Calculate overall risk score from 0-100."""
    score = 20  # baseline

    red_flags = analysis.get("red_flags", [])
    for flag in red_flags:
        if flag.get("severity") == "HIGH":
            score += 20
        elif flag.get("severity") == "MEDIUM":
            score += 10
        else:
            score += 5

    if analysis.get("auto_renewal"):
        score += 15

    if not analysis.get("subletting_allowed", True):
        score += 10

    notice = analysis.get("notice_to_vacate_days", 30)
    if notice > 60:
        score += 10
    elif notice > 30:
        score += 5

    early_term = analysis.get("early_termination_amount", 0)
    if early_term > 3000:
        score += 15
    elif early_term > 1500:
        score += 8

    green_flags = analysis.get("green_flags", [])
    score -= len(green_flags) * 3

    return max(0, min(100, score))


def _save_lease_analysis(analysis: dict) -> None:
    """Save lease analysis to MongoDB for history and pattern learning."""
    try:
        doc = {
            "type": "lease_analysis",
            "filename": analysis.get("filename"),
            "property_name": analysis.get("property_name"),
            "landlord_name": analysis.get("landlord_name"),
            "overall_risk": analysis.get("overall_risk"),
            "risk_score": analysis.get("risk_score"),
            "red_flag_count": len(analysis.get("red_flags", [])),
            "analyzed_at": analysis.get("analyzed_at"),
            "notice_to_vacate_days": analysis.get("notice_to_vacate_days"),
            "auto_renewal": analysis.get("auto_renewal"),
            "subletting_allowed": analysis.get("subletting_allowed"),
        }
        _db.lease_analyses.insert_one(doc)
    except Exception:
        pass  # Non-critical — don't fail the main analysis


def get_lease_history() -> dict[str, Any]:
    """
    Get history of previously analyzed leases.
    Useful for showing patterns across Auburn landlords.
    """
    try:
        analyses = list(
            _db.lease_analyses
            .find({}, {"_id": 0, "filename": 1, "property_name": 1, "landlord_name": 1,
                       "overall_risk": 1, "risk_score": 1, "red_flag_count": 1, "analyzed_at": 1})
            .sort("analyzed_at", -1)
            .limit(10)
        )
        return {
            "success": True,
            "count": len(analyses),
            "analyses": analyses
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
