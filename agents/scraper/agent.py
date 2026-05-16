"""
Nestiq Autonomous Property Scraper Agent
Uses Gemini 2.5 with Google Search grounding to visit apartment websites,
extract real-time pricing, availability, and move-in specials.
Autonomously updates MongoDB when data changes.
"""

import os
import json
import requests
from datetime import datetime
from typing import Any
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai

load_dotenv()

# ── Clients ─────────────────────────────────────────────────────────────────
_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db    = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
_genai = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

# ── Auburn properties with their known website URLs ────────────────────────────
PROPERTY_WEBSITES = {
    "nestiq_001": ("Yugo Auburn North", "yugoauburn.com"),
    "nestiq_002": ("The Grove at Auburn", "groveauburn.com"),
    "nestiq_003": ("oLiv Auburn", "olivauburn.com"),
    "nestiq_004": ("The Magnolia at Auburn", "liveatmagnolia.com"),
    "nestiq_005": ("Logan Square Auburn", "logansquareauburn.com"),
    "nestiq_006": ("Shelton Mill Townhomes", "sheltonmillapartments.com"),
    "nestiq_007": ("1322 North Apartments", "1322north.com"),
    "nestiq_008": ("Lakewood Commons", "lakewoodcommonsauburn.com"),
    "nestiq_009": ("Heritage Terrace", ""),  # Manual lookup needed
    "nestiq_010": ("Old Row at The Balcony", ""),  # Manual lookup needed
    "nestiq_011": ("The Standard at Auburn", "standardatauburn.com"),
    "nestiq_012": ("Samford Square", "samfordsquare.com"),
    "nestiq_013": ("The Union Auburn", "theunionauburn.com"),
    "nestiq_014": ("The Mill at Auburn", "themillatauburn.com"),
    "nestiq_015": ("320 West Mag", "320westmag.com"),
    "nestiq_016": ("The Collective at Auburn", "thecollectiveatauburn.com"),
    "nestiq_017": ("Eagles West Apartments", "eagleswestapartments.com"),
    "nestiq_018": ("The Avenue Auburn", "theavenueauburn.com"),
    "nestiq_019": ("The Boulevard Auburn", "theboulevardauburn.com"),
    "nestiq_020": ("Atlas at Richland Road", "atlasatrichlandroad.com"),
    "nestiq_021": ("Midtown Auburn", "midtownauburn.com"),
}

EXTRACTION_PROMPT = """
You are a real estate data extraction specialist. Visit the apartment website and extract ONLY the following information in valid JSON format. Be precise — do not invent data.

If information is not found on the website, use null. Return ONLY this JSON structure, no other text:

{
  "pricing": {
    "studio": null,
    "one_bed": null,
    "two_bed": null,
    "three_bed": null,
    "four_bed": null,
    "description": "e.g., 'prices vary by floor plan and lease length'"
  },
  "available_now": true or false,
  "available_date": null or "YYYY-MM-DD",
  "move_in_specials": [
    {
      "description": "e.g., '1 month free rent'",
      "value": "e.g., '1 month' or '$500 off'",
      "expiration": "e.g., 'June 30, 2026' or null"
    }
  ],
  "lease_terms": ["6 months", "12 months", "13 months"],
  "waitlist_status": null or "currently on waitlist",
  "new_info": "any other important current info (specials ending soon, price increases, new amenities)"
}
"""


def scrape_property_website(
    property_id: str,
    property_name: str,
    website_url: str,
) -> dict[str, Any]:
    """
    Fetch a property website and use Gemini to extract pricing, availability, and specials.
    Returns extracted data and whether the property has changes.
    """
    if not website_url:
        return {
            "property_id": property_id,
            "status": "skipped",
            "reason": "no website URL known",
            "timestamp": datetime.utcnow().isoformat(),
        }

    try:
        # Fetch the website content
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(f"https://{website_url}", headers=headers, timeout=10)
        response.raise_for_status()
        website_content = response.text[:8000]  # Limit to first 8KB to stay under token limits

        # Use Gemini to analyze the website content
        prompt = f"""
Analyze this website content for {property_name} and extract current apartment information.

WEBSITE CONTENT:
{website_content}

{EXTRACTION_PROMPT}
"""
        genai_response = _genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        # Parse the response
        response_text = genai_response.text.strip()

        # Try to extract JSON from the response
        try:
            # If response starts with ```json, extract it
            if "```json" in response_text:
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                json_str = response_text.split("```")[1].split("```")[0].strip()
            else:
                json_str = response_text

            extracted_data = json.loads(json_str)
        except json.JSONDecodeError:
            return {
                "property_id": property_id,
                "status": "error",
                "reason": "failed to parse response as JSON",
                "raw_response": response_text[:500],
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Get current property data from MongoDB
        current_property = _db.properties.find_one({"property_id": property_id})
        if not current_property:
            return {
                "property_id": property_id,
                "status": "error",
                "reason": "property not found in MongoDB",
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Compare and detect changes
        changes = _detect_changes(current_property, extracted_data)

        # Update MongoDB if there are changes
        if changes["has_changes"]:
            update_doc = {
                "pricing_updated": extracted_data.get("pricing"),
                "available_now": extracted_data.get("available_now"),
                "available_date": extracted_data.get("available_date"),
                "move_in_specials": extracted_data.get("move_in_specials", []),
                "lease_terms_available": extracted_data.get("lease_terms", []),
                "waitlist_status": extracted_data.get("waitlist_status"),
                "last_scraped_at": datetime.utcnow().isoformat(),
            }

            _db.properties.update_one(
                {"property_id": property_id},
                {"$set": update_doc}
            )

            # Log the change
            _db.property_updates.insert_one({
                "property_id": property_id,
                "property_name": property_name,
                "website": website_url,
                "timestamp": datetime.utcnow().isoformat(),
                "changes": changes["details"],
                "extracted_data": extracted_data,
            })

            return {
                "property_id": property_id,
                "status": "updated",
                "changes": changes["details"],
                "new_data": extracted_data,
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            return {
                "property_id": property_id,
                "status": "no_changes",
                "timestamp": datetime.utcnow().isoformat(),
            }

    except Exception as e:
        return {
            "property_id": property_id,
            "status": "error",
            "reason": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }


def _detect_changes(current: dict, new_data: dict) -> dict[str, Any]:
    """
    Compare current MongoDB property data with newly scraped data.
    Returns dict with has_changes boolean and details of what changed.
    """
    changes = []

    # Check pricing changes
    current_pricing = current.get("pricing_updated", current.get("floor_plans", []))
    new_pricing = new_data.get("pricing", {})

    if new_pricing != current_pricing and new_pricing:
        changes.append({
            "field": "pricing",
            "old": current_pricing,
            "new": new_pricing,
        })

    # Check availability
    current_available = current.get("available_now")
    new_available = new_data.get("available_now")
    if new_available is not None and new_available != current_available:
        changes.append({
            "field": "available_now",
            "old": current_available,
            "new": new_available,
        })

    # Check move-in specials
    current_specials = current.get("move_in_specials", [])
    new_specials = new_data.get("move_in_specials", [])
    if new_specials != current_specials:
        changes.append({
            "field": "move_in_specials",
            "old": current_specials,
            "new": new_specials,
        })

    # Check lease terms
    current_terms = current.get("lease_terms_available", [])
    new_terms = new_data.get("lease_terms", [])
    if new_terms != current_terms and new_terms:
        changes.append({
            "field": "lease_terms",
            "old": current_terms,
            "new": new_terms,
        })

    # Check waitlist status
    current_waitlist = current.get("waitlist_status")
    new_waitlist = new_data.get("waitlist_status")
    if new_waitlist and new_waitlist != current_waitlist:
        changes.append({
            "field": "waitlist_status",
            "old": current_waitlist,
            "new": new_waitlist,
        })

    return {
        "has_changes": len(changes) > 0,
        "details": changes,
    }


def scrape_all_properties() -> dict[str, Any]:
    """
    Run the autonomous scraper on all 21 Auburn properties.
    Returns summary of what was updated.
    """
    results = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_properties": len(PROPERTY_WEBSITES),
        "updated": 0,
        "no_changes": 0,
        "errors": 0,
        "skipped": 0,
        "details": [],
    }

    for property_id, (property_name, website_url) in PROPERTY_WEBSITES.items():
        result = scrape_property_website(property_id, property_name, website_url)
        results["details"].append(result)

        if result["status"] == "updated":
            results["updated"] += 1
        elif result["status"] == "no_changes":
            results["no_changes"] += 1
        elif result["status"] == "error":
            results["errors"] += 1
        elif result["status"] == "skipped":
            results["skipped"] += 1

    return results


if __name__ == "__main__":
    # Run scraper on all properties
    summary = scrape_all_properties()
    print(json.dumps(summary, indent=2))
