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


def _safe_number(value, default=0):
    """Convert numeric-looking values to a number, otherwise use default."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).replace("$", "").replace(",", "").strip())
    except Exception:
        return default


def _format_property(doc: dict, roommates: int = 1) -> dict:
    """Format a MongoDB property document for agent consumption.

    Handles both original seeded properties and newer auto-discovered properties,
    which may have partial rent/floor-plan data.
    """
    floor_plans = doc.get("floor_plans") or []

    # Find best floor plan for roommate count, ignoring plans with missing rent.
    best_plan = None
    best_rent = None

    for fp in floor_plans:
        if not isinstance(fp, dict):
            continue

        beds = _safe_number(fp.get("beds"), 1)
        rent = fp.get("rent_per_person")
        if rent is None:
            rent = fp.get("rent")

        rent = _safe_number(rent, None)

        if beds >= roommates and rent is not None:
            if best_plan is None or rent < best_rent:
                best_plan = fp
                best_rent = rent

    # If no roommate-matching plan has rent, use the cheapest available plan with rent.
    if best_plan is None and floor_plans:
        valid_plans = []
        for fp in floor_plans:
            if not isinstance(fp, dict):
                continue
            rent = fp.get("rent_per_person")
            if rent is None:
                rent = fp.get("rent")
            rent = _safe_number(rent, None)
            if rent is not None:
                valid_plans.append((rent, fp))

        if valid_plans:
            best_rent, best_plan = min(valid_plans, key=lambda item: item[0])

    # Fallback to property-level rent fields.
    rent_per_person = best_rent
    if rent_per_person is None:
        rent_per_person = doc.get("rent_per_person")
    if rent_per_person is None:
        rent_per_person = doc.get("rent_min")

    rent_known = rent_per_person is not None
    rent_for_math = _safe_number(rent_per_person, 0) if rent_known else 0
    rent_per_person = rent_for_math if rent_known else None

    total_rent = rent_for_math * roommates if rent_known else None

    utilities = _safe_number(doc.get("utilities_estimate_monthly"), 100)

    fees = doc.get("fees") or {}
    if not isinstance(fees, dict):
        fees = {}

    pet_monthly = _safe_number(fees.get("pet_monthly"), 0)
    admin_fee = _safe_number(fees.get("admin_fee"), 0)
    application_fee = _safe_number(fees.get("application_fee"), 0)
    security_deposit = _safe_number(fees.get("security_deposit"), 0)
    pet_deposit = _safe_number(fees.get("pet_deposit"), 0)

    # True annual cost per person
    annual_cost = None
    if rent_known:
        annual_cost = (rent_for_math + utilities + pet_monthly) * 12
        annual_cost += admin_fee + application_fee

    move_in_cost = security_deposit + pet_deposit + application_fee

    amenities = doc.get("amenities") or {}

    if isinstance(amenities, dict):
        amenity_list = [k.replace("_", " ") for k, v in amenities.items() if v]
        pet_friendly = bool(amenities.get("pet_friendly", False))
        furnished = bool(amenities.get("furnished", False))
        pool = bool(amenities.get("pool", False))
        gym = bool(amenities.get("gym", False))
        study_rooms = bool(amenities.get("study_rooms", False))
        wifi_included = bool(amenities.get("wifi_included", False))
    elif isinstance(amenities, list):
        amenity_list = [str(a) for a in amenities if a]
        amenity_text = " ".join(amenity_list).lower()
        pet_friendly = "pet" in amenity_text
        furnished = "furnished" in amenity_text
        pool = "pool" in amenity_text
        gym = "gym" in amenity_text or "fitness" in amenity_text
        study_rooms = "study" in amenity_text
        wifi_included = "wifi" in amenity_text or "internet" in amenity_text
    else:
        amenity_list = []
        pet_friendly = False
        furnished = False
        pool = False
        gym = False
        study_rooms = False
        wifi_included = False

    return {
        "property_id": doc.get("property_id"),
        "name": doc.get("name"),
        "address": doc.get("address"),
        "website": doc.get("website"),
        "housing_category": doc.get("housing_category"),
        "status": doc.get("status"),
        "enrichment_status": doc.get("enrichment_status"),

        "distance_to_campus_miles": doc.get("distance_to_campus_miles"),
        "walk_time_minutes": doc.get("walk_time_minutes"),
        "drive_time_minutes": doc.get("drive_time_minutes"),
        "tiger_transit": doc.get("tiger_transit", False),

        "rent_per_person": rent_per_person,
        "rent_min": doc.get("rent_min"),
        "rent_max": doc.get("rent_max"),
        "rent_notes": doc.get("rent_notes"),
        "total_rent_for_group": total_rent,
        "utilities_estimate": utilities,
        "true_cost_per_person_monthly": rent_for_math + utilities if rent_known else None,
        "annual_cost_per_person": annual_cost,
        "move_in_cost": move_in_cost,

        "beds": best_plan.get("beds") if isinstance(best_plan, dict) else None,
        "sqft": best_plan.get("sqft") if isinstance(best_plan, dict) else None,
        "floor_plans": floor_plans[:5],

        "amenities": amenity_list,
        "pet_friendly": pet_friendly,
        "furnished": furnished,
        "pool": pool,
        "gym": gym,
        "study_rooms": study_rooms,
        "wifi_included": wifi_included,

        "available_date": doc.get("available_date"),
        "availability_status": doc.get("availability_status"),
        "reputation_score": doc.get("reputation_score") or doc.get("google_rating"),
        "google_rating": doc.get("google_rating"),
        "google_review_count": doc.get("google_review_count"),
        "price_tier": doc.get("price_tier"),
        "landlord_id": doc.get("landlord_id"),
        "tags": doc.get("tags", []),
        "description": (doc.get("description") or "")[:300],
    }


# ── Tool 1: Semantic Property Search ────────────────────────────────────────
def search_properties_by_description(
    query: str,
    roommates: int = 1,
    max_rent_per_person: int = 2000,
    pet_friendly: bool = False,
    furnished: bool = False,
    limit: int = 10,
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
                    "numCandidates": 200,
                    "limit": limit * 3,
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
                    "$or": [
                        {"floor_plans.rent_per_person": {"$lte": max_rent_per_person}},
                        {"rent_min": {"$lte": max_rent_per_person}},
                        {"rent_min": None},
                        {"rent_min": {"$exists": False}},
                         {"rent_per_person": None},
            {"rent_per_person": {"$exists": False}},
                    ]
                }
            },
            {"$limit": limit * 2}

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
    max_distance_miles: float = 5.0,
    pet_friendly: bool = False,
    furnished: bool = False,
    pool: bool = False,
    gym: bool = False,
    tiger_transit: bool = False,
    price_tier: str = "",
    limit: int = 12,
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
            "$and": [
                {"distance_to_campus_miles": {"$lte": max_distance_miles}},
                {
                    "$or": [
                        {
                            "floor_plans": {
                                "$elemMatch": {
                                    "beds": {"$gte": min_beds},
                                    "rent_per_person": {"$lte": max_rent_per_person}
                                }
                            }
                        },
                        {"rent_min": {"$lte": max_rent_per_person}},
                        {"rent_min": None},
                        {"rent_min": {"$exists": False}},
                        {"rent_per_person": None},
{"rent_per_person": {"$exists": False}},
                    ]
                }
            ]
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
