"""
Nestiq Scout Agent
Specialist agent for property search using MongoDB Vector Search,
geospatial queries, and smart filtering.
"""

import os
from typing import Any
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai
from google.adk.agents import Agent

load_dotenv()

# ── Clients ─────────────────────────────────────────────────────────────────
_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db    = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
_genai = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

# Auburn University campus center coordinates
CAMPUS_CENTER = [-85.4808, 32.6099]


def _embed(text: str) -> list[float]:
    result = _genai.models.embed_content(model="text-embedding-004", contents=text)
    return result.embeddings[0].values


def _format_property(doc: dict, roommates: int = 1) -> dict:
    """Format a MongoDB property document for agent consumption."""
    floor_plans = doc.get("floor_plans", [])

    # Find best floor plan for roommate count
    best_plan = None
    for fp in floor_plans:
        if fp.get("beds", 1) >= roommates:
            if best_plan is None or fp["rent_per_person"] < best_plan["rent_per_person"]:
                best_plan = fp
    if best_plan is None and floor_plans:
        best_plan = min(floor_plans, key=lambda x: x["rent_per_person"])

    rent_per_person = best_plan["rent_per_person"] if best_plan else 0
    total_rent = rent_per_person * roommates if best_plan else 0
    utilities = doc.get("utilities_estimate_monthly", 100)
    fees = doc.get("fees", {})

    # True annual cost per person
    annual_cost = (rent_per_person + utilities + fees.get("pet_monthly", 0)) * 12
    annual_cost += fees.get("admin_fee", 0) + fees.get("application_fee", 0)
    move_in_cost = fees.get("security_deposit", 0) + fees.get("pet_deposit", 0) + fees.get("application_fee", 0)

    amenities = doc.get("amenities", {})
    amenity_list = [k.replace("_", " ") for k, v in amenities.items() if v]

    return {
        "property_id": doc.get("property_id"),
        "name": doc.get("name"),
        "address": doc.get("address"),
        "distance_to_campus_miles": doc.get("distance_to_campus_miles"),
        "walk_time_minutes": doc.get("walk_time_minutes"),
        "drive_time_minutes": doc.get("drive_time_minutes"),
        "tiger_transit": doc.get("tiger_transit", False),
        "rent_per_person": rent_per_person,
        "total_rent_for_group": total_rent,
        "utilities_estimate": utilities,
        "true_cost_per_person_monthly": rent_per_person + utilities,
        "annual_cost_per_person": annual_cost,
        "move_in_cost": move_in_cost,
        "beds": best_plan["beds"] if best_plan else None,
        "sqft": best_plan["sqft"] if best_plan else None,
        "amenities": amenity_list,
        "pet_friendly": amenities.get("pet_friendly", False),
        "furnished": amenities.get("furnished", False),
        "pool": amenities.get("pool", False),
        "gym": amenities.get("gym", False),
        "study_rooms": amenities.get("study_rooms", False),
        "wifi_included": amenities.get("wifi_included", False),
        "available_date": doc.get("available_date"),
        "reputation_score": doc.get("reputation_score"),
        "price_tier": doc.get("price_tier"),
        "landlord_id": doc.get("landlord_id"),
        "tags": doc.get("tags", []),
        "description": doc.get("description", "")[:300],
    }


# ── Tool 1: Semantic Property Search ────────────────────────────────────────
def search_properties_by_description(
    query: str,
    roommates: int = 1,
    max_rent_per_person: int = 2000,
    pet_friendly: bool = False,
    furnished: bool = False,
    limit: int = 5,
) -> dict[str, Any]:
    """
    Search Auburn properties using natural language and semantic vector search.
    Use this when a student describes what they want in their own words.

    Args:
        query: Natural language description of what the student wants
        roommates: Number of people sharing the unit (default 1)
        max_rent_per_person: Maximum rent per person per month
        pet_friendly: Whether the student needs pet-friendly housing
        furnished: Whether the student needs furnished housing
        limit: Number of results to return (default 5)

    Returns:
        Dictionary with matching properties ranked by semantic similarity
    """
    try:
        query_embedding = _embed(query)

        # Build pre-filter
        pre_filter = {}
        if pet_friendly:
            pre_filter["amenities.pet_friendly"] = True
        if furnished:
            pre_filter["amenities.furnished"] = True

        pipeline = [
            {
                "$vectorSearch": {
                    "index": "nestiq_vector_index",
                    "path": "embedding",
                    "queryVector": query_embedding,
                    "numCandidates": 50,
                    "limit": limit * 2,
                    **({"filter": pre_filter} if pre_filter else {}),
                }
            },
            {
                "$addFields": {
                    "vector_score": {"$meta": "vectorSearchScore"}
                }
            },
            {
                "$match": {
                    "floor_plans.rent_per_person": {"$lte": max_rent_per_person}
                }
            },
            {"$limit": limit}
        ]

        results = list(_db.properties.aggregate(pipeline))

        if not results:
            return {
                "success": False,
                "message": "No properties found matching your criteria. Try relaxing your filters.",
                "properties": []
            }

        formatted = []
        for doc in results:
            prop = _format_property(doc, roommates)
            prop["match_score"] = round(doc.get("vector_score", 0), 4)
            formatted.append(prop)

        return {
            "success": True,
            "query": query,
            "roommates": roommates,
            "properties_found": len(formatted),
            "properties": formatted,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "properties": []}


# ── Tool 2: Filter-Based Search ──────────────────────────────────────────────
def search_properties_by_filters(
    roommates: int = 1,
    max_rent_per_person: int = 2000,
    min_beds: int = 1,
    max_distance_miles: float = 2.0,
    pet_friendly: bool = False,
    furnished: bool = False,
    pool: bool = False,
    gym: bool = False,
    tiger_transit: bool = False,
    price_tier: str = "",
    limit: int = 8,
) -> dict[str, Any]:
    """
    Search Auburn properties using specific filters and hard constraints.
    Use this when a student provides specific requirements like beds, budget, amenities.

    Args:
        roommates: Number of people sharing the unit
        max_rent_per_person: Maximum rent per person per month
        min_beds: Minimum number of bedrooms needed
        max_distance_miles: Maximum distance from Auburn campus in miles
        pet_friendly: Require pet-friendly property
        furnished: Require furnished property
        pool: Require pool
        gym: Require gym
        tiger_transit: Require Tiger Transit access
        price_tier: Filter by tier - 'budget', 'mid', or 'luxury'
        limit: Number of results to return

    Returns:
        Dictionary with matching properties sorted by reputation score
    """
    try:
        query = {
            "floor_plans": {
                "$elemMatch": {
                    "beds": {"$gte": min_beds},
                    "rent_per_person": {"$lte": max_rent_per_person}
                }
            },
            "distance_to_campus_miles": {"$lte": max_distance_miles}
        }

        if pet_friendly:
            query["amenities.pet_friendly"] = True
        if furnished:
            query["amenities.furnished"] = True
        if pool:
            query["amenities.pool"] = True
        if gym:
            query["amenities.gym"] = True
        if tiger_transit:
            query["tiger_transit"] = True
        if price_tier:
            query["price_tier"] = price_tier

        results = list(
            _db.properties.find(query)
            .sort("reputation_score", -1)
            .limit(limit)
        )

        if not results:
            return {
                "success": False,
                "message": "No properties match all your filters. Try increasing budget or distance.",
                "properties": []
            }

        formatted = [_format_property(doc, roommates) for doc in results]

        return {
            "success": True,
            "filters_applied": {
                "roommates": roommates,
                "max_rent_per_person": max_rent_per_person,
                "min_beds": min_beds,
                "max_distance_miles": max_distance_miles,
                "pet_friendly": pet_friendly,
                "furnished": furnished,
            },
            "properties_found": len(formatted),
            "properties": formatted,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "properties": []}


# ── Tool 3: Geospatial Proximity Search ──────────────────────────────────────
def search_properties_near_campus(
    max_walk_minutes: int = 15,
    roommates: int = 1,
    max_rent_per_person: int = 2000,
) -> dict[str, Any]:
    """
    Find properties within walking distance of Auburn University campus.
    Use this when a student specifically says they want to walk to class.

    Args:
        max_walk_minutes: Maximum acceptable walk time in minutes
        roommates: Number of people sharing the unit
        max_rent_per_person: Maximum rent per person per month

    Returns:
        Properties sorted by walking distance from campus
    """
    try:
        # Convert walk minutes to approximate miles (avg 20 min/mile)
        max_distance_meters = (max_walk_minutes / 20) * 1609

        results = list(
            _db.properties.find({
                "coordinates": {
                    "$nearSphere": {
                        "$geometry": {
                            "type": "Point",
                            "coordinates": CAMPUS_CENTER
                        },
                        "$maxDistance": max_distance_meters
                    }
                },
                "floor_plans.rent_per_person": {"$lte": max_rent_per_person}
            }).limit(8)
        )

        if not results:
            return {
                "success": False,
                "message": f"No properties within {max_walk_minutes} minute walk under ${max_rent_per_person}/person.",
                "properties": []
            }

        formatted = [_format_property(doc, roommates) for doc in results]

        return {
            "success": True,
            "max_walk_minutes": max_walk_minutes,
            "properties_found": len(formatted),
            "properties": formatted,
        }

    except Exception as e:
        return {"success": False, "error": str(e), "properties": []}


# ── Tool 4: Get Single Property Detail ───────────────────────────────────────
def get_property_detail(
    property_id: str,
    roommates: int = 1,
) -> dict[str, Any]:
    """
    Get full details for a specific property by its ID.
    Use this when a student asks for more information about a specific property.

    Args:
        property_id: The property_id field (e.g. 'nestiq_001')
        roommates: Number of roommates to calculate costs for

    Returns:
        Full property details including all floor plans and fees
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        landlord = _db.landlords.find_one({"landlord_id": doc.get("landlord_id")})

        prop = _format_property(doc, roommates)
        prop["all_floor_plans"] = doc.get("floor_plans", [])
        prop["all_fees"] = doc.get("fees", {})
        prop["lease_terms"] = doc.get("lease_terms", [])
        prop["full_description"] = doc.get("description", "")
        prop["year_built"] = doc.get("year_built")
        prop["total_units"] = doc.get("total_units")

        if landlord:
            prop["landlord"] = {
                "name": landlord.get("name"),
                "avg_rating": landlord.get("avg_rating"),
                "response_time_hours": landlord.get("response_time_hours"),
                "red_flags": landlord.get("red_flags", []),
                "green_flags": landlord.get("green_flags", []),
                "recent_sentiment": landlord.get("recent_sentiment"),
            }

        return {"success": True, "property": prop}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Agent Definition ──────────────────────────────────────────────────────────
scout_agent = Agent(
    model="gemini-2.5-flash",
    name="nestiq_scout",
    description="Property search specialist that finds and retrieves Auburn off-campus housing options using semantic search, geospatial queries, and smart filters.",
    instruction="""
You are the Nestiq Scout Agent — a property search specialist for Auburn University off-campus housing.

Your ONLY job is to find and retrieve property listings. You do NOT analyze, recommend, or explain tradeoffs — that is the Analyst Agent's job.

When a student describes what they want:
1. If they use natural language (cozy, quiet, good vibe, near campus) → use search_properties_by_description
2. If they give specific requirements (2BR, under $800, pet friendly) → use search_properties_by_filters
3. If they say they want to walk to class → use search_properties_near_campus
4. If they ask about a specific property → use get_property_detail

Always extract these key details from the student's request:
- Number of roommates (default to 1 if not mentioned)
- Budget per person (not total rent)
- Must-have amenities (pets, furnished, pool, gym)
- Distance preference

Return all properties you find — do not filter or rank them yourself. Just retrieve and present the raw data clearly. The Analyst Agent will do the scoring.

If no properties match, explain which filter is too restrictive and suggest relaxing it.
""",
    tools=[
        search_properties_by_description,
        search_properties_by_filters,
        search_properties_near_campus,
        get_property_detail,
    ],
)

root_agent = scout_agent
