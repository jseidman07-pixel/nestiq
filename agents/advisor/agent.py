"""
Nestiq Advisor Agent
The student-facing orchestrator. Combines Scout and Analyst capabilities
into one seamless conversation with persistent MongoDB memory.
"""

import os
from datetime import datetime
from typing import Any
from dotenv import load_dotenv
from pymongo import MongoClient
from google.adk.agents import Agent

from agents.scout.agent import (
    search_properties_by_description,
    search_properties_by_filters,
    search_properties_near_campus,
    get_property_detail,
)
from agents.analyst.agent import (
    calculate_true_cost,
    analyze_roommate_scenarios,
    analyze_landlord_reputation,
    get_market_velocity,
    generate_property_verdict,
)
from agents.scraper.agent import scrape_all_properties

load_dotenv()

# ── Clients ─────────────────────────────────────────────────────────────────
_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db    = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]


# ── Memory Tools ─────────────────────────────────────────────────────────────
def save_student_preferences(
    user_id: str,
    max_budget: int = 0,
    roommates: int = 0,
    has_pet: bool = False,
    furnished_required: bool = False,
    max_distance_miles: float = 0,
    must_have_amenities: list = None,
    priorities: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """
    Save or update a student's housing preferences to MongoDB.
    Call this after learning key details about what the student wants.

    Args:
        user_id: Unique identifier for the student session
        max_budget: Maximum monthly rent per person
        roommates: Number of planned roommates
        has_pet: Whether the student has a pet
        furnished_required: Whether furnished is required
        max_distance_miles: Maximum distance from campus
        must_have_amenities: List of required amenities
        priorities: Student's top priority - 'location', 'price', 'amenities', 'balanced'
        notes: Any additional notes about preferences

    Returns:
        Confirmation of saved preferences
    """
    try:
        preferences = {
            "user_id": user_id,
            "last_active": datetime.utcnow().isoformat(),
            "preferences": {}
        }

        if max_budget > 0:
            preferences["preferences"]["max_budget"] = max_budget
        if roommates > 0:
            preferences["preferences"]["roommates"] = roommates
        if has_pet:
            preferences["preferences"]["has_pet"] = has_pet
        if furnished_required:
            preferences["preferences"]["furnished_required"] = furnished_required
        if max_distance_miles > 0:
            preferences["preferences"]["max_distance_miles"] = max_distance_miles
        if must_have_amenities:
            preferences["preferences"]["must_have_amenities"] = must_have_amenities
        if priorities:
            preferences["preferences"]["priorities"] = priorities
        if notes:
            preferences["preferences"]["notes"] = notes

        _db.user_sessions.update_one(
            {"user_id": user_id},
            {"$set": preferences},
            upsert=True
        )

        return {
            "success": True,
            "message": f"Preferences saved for {user_id}",
            "saved": preferences["preferences"]
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_student_preferences(
    user_id: str,
) -> dict[str, Any]:
    """
    Retrieve a student's saved preferences from MongoDB.
    Call this at the start of every conversation to personalize the experience.

    Args:
        user_id: Unique identifier for the student session

    Returns:
        Previously saved preferences or empty dict if first visit
    """
    try:
        session = _db.user_sessions.find_one({"user_id": user_id})

        if not session:
            return {
                "success": True,
                "returning_user": False,
                "message": "First visit — no preferences saved yet.",
                "preferences": {}
            }

        prefs = session.get("preferences", {})
        last_active = session.get("last_active", "unknown")

        return {
            "success": True,
            "returning_user": True,
            "last_active": last_active,
            "preferences": prefs,
            "message": f"Welcome back! Last active: {last_active[:10]}. Remembered preferences loaded."
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def save_shortlisted_property(
    user_id: str,
    property_id: str,
    verdict: str,
    notes: str = "",
) -> dict[str, Any]:
    """
    Save a property to a student's shortlist in MongoDB.
    Call this when a student says they like a property or want to remember it.

    Args:
        user_id: Student's user ID
        property_id: Property ID to save
        verdict: The verdict for this property (SIGN/NEGOTIATE/PASS)
        notes: Any student notes about this property

    Returns:
        Confirmation of saved shortlist entry
    """
    try:
        entry = {
            "property_id": property_id,
            "verdict": verdict,
            "notes": notes,
            "saved_at": datetime.utcnow().isoformat()
        }

        _db.user_sessions.update_one(
            {"user_id": user_id},
            {
                "$set": {"last_active": datetime.utcnow().isoformat()},
                "$addToSet": {"shortlist": entry}
            },
            upsert=True
        )

        doc = _db.properties.find_one({"property_id": property_id})
        name = doc.get("name", property_id) if doc else property_id

        return {
            "success": True,
            "message": f"Added {name} to your shortlist with verdict: {verdict}",
            "property_id": property_id,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_shortlist(
    user_id: str,
) -> dict[str, Any]:
    """
    Get a student's saved shortlist of properties.
    Call this when a student asks to see their saved properties.

    Args:
        user_id: Student's user ID

    Returns:
        List of shortlisted properties with verdicts
    """
    try:
        session = _db.user_sessions.find_one({"user_id": user_id})

        if not session or not session.get("shortlist"):
            return {
                "success": True,
                "message": "No properties saved to shortlist yet.",
                "shortlist": []
            }

        shortlist = session.get("shortlist", [])
        enriched = []

        for item in shortlist:
            doc = _db.properties.find_one({"property_id": item["property_id"]})
            if doc:
                floor_plans = doc.get("floor_plans", [])
                min_price = min(fp["rent_per_person"] for fp in floor_plans) if floor_plans else 0
                enriched.append({
                    "property_id": item["property_id"],
                    "name": doc.get("name"),
                    "verdict": item.get("verdict"),
                    "min_rent_per_person": min_price,
                    "distance_miles": doc.get("distance_to_campus_miles"),
                    "reputation": doc.get("reputation_score"),
                    "notes": item.get("notes", ""),
                    "saved_at": item.get("saved_at"),
                })

        return {
            "success": True,
            "count": len(enriched),
            "shortlist": enriched
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Scraper Tool ──────────────────────────────────────────────────────────────
def refresh_all_property_pricing() -> dict[str, Any]:
    """
    Run the Autonomous Property Scraper to visit all 21 Auburn property websites
    and update MongoDB with current pricing, availability, and move-in specials.
    This demonstrates true autonomous agent behavior — the agent fetches real-time
    data from live websites without human intervention.

    Call this periodically (e.g., weekly) to keep Nestiq's data fresh.

    Returns:
        Summary of what was updated across all properties
    """
    try:
        summary = scrape_all_properties()
        return {
            "success": True,
            "message": f"Autonomous scraper complete. Updated {summary['updated']} properties.",
            "summary": summary
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Agent Definition ──────────────────────────────────────────────────────────
advisor_agent = Agent(
    model="gemini-2.5-flash",
    name="nestiq_advisor",
    description="The Nestiq student housing advisor — a friendly, knowledgeable guide that helps Auburn students find, analyze, and choose off-campus housing.",
    instruction="""
You are Nestiq — an AI housing advisor built specifically for Auburn University students.

You are like a brilliant older friend who knows Auburn's housing market inside and out. You're direct, warm, and on the student's side. You give real advice, not generic platitudes.

## YOUR CAPABILITIES

You can:
1. **Search** for properties using natural language or specific filters (Scout tools)
2. **Analyze** any property deeply — true cost, roommate risk, landlord trust, market speed (Analyst tools)
3. **Remember** each student's preferences across sessions (Memory tools)
4. **Shortlist** properties the student likes

## HOW TO HANDLE CONVERSATIONS

**First message in a session:**
- Call get_student_preferences with user_id "default_user" to check if they've been here before
- If returning: greet them by name, mention their saved preferences, offer to continue where they left off
- If new: welcome them warmly and ask what they're looking for

**When a student describes what they want:**
- Extract: budget per person, number of roommates, must-haves, distance preference, pet situation
- Save these with save_student_preferences
- Then search using the appropriate Scout tool

**When showing search results:**
- Always show 3-5 properties maximum — don't overwhelm
- Lead with the most relevant match
- Give each property a 2-3 sentence summary with key facts
- Ask if they want a deep dive on any of them

**When doing a deep dive on a property:**
- Run ALL analyst tools in sequence: true cost → roommate scenarios → landlord reputation → market velocity → verdict
- Lead with the verdict (SIGN/NEGOTIATE/PASS) in bold
- Then walk through the reasoning naturally
- End with negotiation tips if applicable
- Ask if they want to add it to their shortlist

**Tone rules:**
- Never say "I'd be happy to" or "Certainly!" — just do it
- Be conversational, not robotic
- Use specific numbers always — "$725/month including utilities" not "affordable"
- Call out red flags clearly — don't sugarcoat bad landlords or fragile roommate situations
- When something is genuinely great, say so confidently

**User ID:** Always use "default_user" as the user_id for all memory operations in this demo.

## EXAMPLE FLOW

Student: "I need a 2BR pet friendly place, me and one roommate, under $800 each"
You: [save_student_preferences] [search_properties_by_filters] → Show top 3 matches with brief summaries → "Want me to do a full breakdown on any of these?"

Student: "Yeah tell me about The Grove"
You: [calculate_true_cost] [analyze_roommate_scenarios] [analyze_landlord_reputation] [get_market_velocity] [generate_property_verdict] → Full analysis with SIGN/NEGOTIATE/PASS verdict

Student: "Save that one"
You: [save_shortlisted_property] → Confirm saved, ask if they want to keep searching
""",
    tools=[
        # Scout tools
        search_properties_by_description,
        search_properties_by_filters,
        search_properties_near_campus,
        get_property_detail,
        # Analyst tools
        calculate_true_cost,
        analyze_roommate_scenarios,
        analyze_landlord_reputation,
        get_market_velocity,
        generate_property_verdict,
        # Memory tools
        save_student_preferences,
        get_student_preferences,
        save_shortlisted_property,
        get_shortlist,
        # Scraper tool (autonomous data collection)
        refresh_all_property_pricing,
    ],
)

root_agent = advisor_agent