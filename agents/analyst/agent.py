"""
Nestiq Analyst Agent
Specialist agent for deep property analysis:
- True cost calculation
- Roommate fragility simulation
- Market velocity scoring
- Landlord reputation analysis
- Sign / Negotiate / Wait verdict
"""

import os
from typing import Any
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from google.adk.agents import Agent

load_dotenv()

# ── Clients ─────────────────────────────────────────────────────────────────
_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db    = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]

# Auburn market averages (based on research)
MARKET_AVERAGES = {
    "budget": {"avg_rent": 612, "avg_rating": 3.7},
    "mid":    {"avg_rent": 789, "avg_rating": 4.1},
    "luxury": {"avg_rent": 1149, "avg_rating": 4.4},
}


# ── Tool 1: True Cost Analysis ───────────────────────────────────────────────
def calculate_true_cost(
    property_id: str,
    roommates: int = 1,
    has_pet: bool = False,
    lease_months: int = 12,
) -> dict[str, Any]:
    """
    Calculate the complete true cost of living at a property.
    Goes beyond rent to include utilities, fees, deposits, and pet costs.

    Args:
        property_id: The property ID to analyze
        roommates: Number of people splitting the unit
        has_pet: Whether the student has a pet
        lease_months: Length of lease in months

    Returns:
        Full cost breakdown per person including all hidden fees
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        floor_plans = doc.get("floor_plans", [])
        fees = doc.get("fees", {})

        # Find best floor plan for roommate count
        best_plan = None
        for fp in floor_plans:
            if fp.get("beds", 1) >= roommates:
                if best_plan is None or fp["rent_per_person"] < best_plan["rent_per_person"]:
                    best_plan = fp
        if not best_plan and floor_plans:
            best_plan = min(floor_plans, key=lambda x: x["rent_per_person"])

        rent_per_person = best_plan["rent_per_person"] if best_plan else 0
        utilities = doc.get("utilities_estimate_monthly", 100)

        # Adjust utilities if included
        if doc.get("amenities", {}).get("utilities_included"):
            utilities = 0
        if doc.get("amenities", {}).get("wifi_included"):
            utilities -= 40  # WiFi typically $40/mo

        utilities = max(0, utilities)

        # Pet costs
        pet_monthly = fees.get("pet_monthly", 0) if has_pet else 0
        pet_deposit = fees.get("pet_deposit", 0) if has_pet else 0

        # Monthly costs per person
        monthly_rent = rent_per_person
        monthly_utilities = utilities
        monthly_pet = pet_monthly
        monthly_total = monthly_rent + monthly_utilities + monthly_pet

        # One-time costs per person
        security_deposit = fees.get("security_deposit", 0)
        application_fee = fees.get("application_fee", 0)
        admin_fee = fees.get("admin_fee", 0)
        move_in_total = security_deposit + application_fee + admin_fee + pet_deposit

        # Full lease cost
        lease_total = (monthly_total * lease_months) + move_in_total

        # Annual equivalent
        annual_cost = monthly_total * 12

        # Compare to market average
        tier = doc.get("price_tier", "mid")
        market_avg = MARKET_AVERAGES.get(tier, MARKET_AVERAGES["mid"])["avg_rent"]
        vs_market = rent_per_person - market_avg
        vs_market_pct = round((vs_market / market_avg) * 100, 1)

        return {
            "success": True,
            "property_name": doc.get("name"),
            "property_id": property_id,
            "roommates": roommates,
            "cost_breakdown": {
                "monthly_rent_per_person": monthly_rent,
                "monthly_utilities_estimate": monthly_utilities,
                "monthly_pet_cost": monthly_pet,
                "monthly_total_per_person": monthly_total,
                "annual_cost_per_person": annual_cost,
                "full_lease_cost_per_person": lease_total,
            },
            "move_in_costs": {
                "security_deposit": security_deposit,
                "application_fee": application_fee,
                "admin_fee": admin_fee,
                "pet_deposit": pet_deposit,
                "total_move_in": move_in_total,
            },
            "market_comparison": {
                "your_rent": rent_per_person,
                "market_average_for_tier": market_avg,
                "difference": vs_market,
                "percent_vs_market": vs_market_pct,
                "assessment": "above market" if vs_market > 50 else "below market" if vs_market < -50 else "at market",
            },
            "wifi_included": doc.get("amenities", {}).get("wifi_included", False),
            "utilities_included": doc.get("amenities", {}).get("utilities_included", False),
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool 2: Roommate Fragility Analysis ──────────────────────────────────────
def analyze_roommate_scenarios(
    property_id: str,
    planned_roommates: int,
) -> dict[str, Any]:
    """
    Simulate what happens financially if one or more roommates drop out.
    This is the roommate fragility score — critical for choosing a lease.

    Args:
        property_id: The property ID to analyze
        planned_roommates: Number of roommates you plan to have

    Returns:
        Cost scenarios for different roommate counts and fragility score
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        floor_plans = doc.get("floor_plans", [])
        utilities = doc.get("utilities_estimate_monthly", 100)

        # Find the target floor plan
        target_plan = None
        for fp in floor_plans:
            if fp.get("beds", 1) >= planned_roommates:
                if target_plan is None or fp["rent_per_person"] < target_plan["rent_per_person"]:
                    target_plan = fp

        if not target_plan and floor_plans:
            target_plan = min(floor_plans, key=lambda x: abs(x.get("beds", 1) - planned_roommates))

        if not target_plan:
            return {"success": False, "error": "No suitable floor plan found"}

        total_unit_rent = target_plan["rent_per_person"] * target_plan["beds"]
        beds = target_plan["beds"]

        scenarios = []
        for n in range(planned_roommates, 0, -1):
            cost_per_person = total_unit_rent / n
            monthly_with_utilities = cost_per_person + utilities
            affordable = cost_per_person <= 900

            scenarios.append({
                "roommates": n,
                "rent_per_person": round(cost_per_person, 2),
                "total_with_utilities": round(monthly_with_utilities, 2),
                "affordable": affordable,
                "status": "comfortable" if cost_per_person <= 750 else "manageable" if cost_per_person <= 900 else "tight" if cost_per_person <= 1100 else "unaffordable",
            })

        # Fragility score: how many roommates can drop before it's unaffordable
        affordable_scenarios = [s for s in scenarios if s["affordable"]]
        fragility_score = len(affordable_scenarios)
        max_fragility = planned_roommates

        if fragility_score == max_fragility:
            fragility_rating = "RESILIENT"
            fragility_note = f"Stays affordable even if all roommates leave except 1."
        elif fragility_score >= max_fragility - 1:
            fragility_rating = "MODERATE"
            fragility_note = f"Affordable with {fragility_score} roommates. Gets tight if someone leaves."
        else:
            fragility_rating = "FRAGILE"
            fragility_note = f"Only works with all {planned_roommates} roommates. One dropout is a crisis."

        return {
            "success": True,
            "property_name": doc.get("name"),
            "property_id": property_id,
            "floor_plan": {
                "beds": beds,
                "total_monthly_rent": total_unit_rent,
            },
            "planned_roommates": planned_roommates,
            "scenarios": scenarios,
            "fragility_rating": fragility_rating,
            "fragility_score": f"{fragility_score}/{max_fragility} scenarios affordable",
            "fragility_note": fragility_note,
            "recommendation": "Safe choice" if fragility_rating == "RESILIENT" else "Proceed with caution" if fragility_rating == "MODERATE" else "High risk — have a backup plan",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool 3: Landlord & Reputation Analysis ───────────────────────────────────
def analyze_landlord_reputation(
    property_id: str,
) -> dict[str, Any]:
    """
    Deep dive into landlord reputation signals for a property.
    Surfaces red flags, green flags, and an overall trust score.

    Args:
        property_id: The property ID to analyze

    Returns:
        Full landlord reputation analysis with trust score and recommendation
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        landlord = _db.landlords.find_one({"landlord_id": doc.get("landlord_id")})
        if not landlord:
            return {"success": False, "error": "Landlord data not found"}

        rating = landlord.get("avg_rating", 3.0)
        response_time = landlord.get("response_time_hours", 24)
        red_flags = landlord.get("red_flags", [])
        green_flags = landlord.get("green_flags", [])
        reviews = landlord.get("total_reviews", 0)
        sentiment = landlord.get("recent_sentiment", "unknown")

        # Calculate trust score (0-100)
        trust_score = 0
        trust_score += min(rating / 5 * 40, 40)  # Rating: up to 40 pts
        trust_score += max(0, 20 - response_time)  # Response time: up to 20 pts
        trust_score += min(reviews / 50 * 20, 20)  # Review volume: up to 20 pts
        trust_score += len(green_flags) * 3  # Green flags: 3 pts each
        trust_score -= len(red_flags) * 5  # Red flags: -5 pts each
        if sentiment == "very positive":
            trust_score += 10
        elif sentiment == "positive":
            trust_score += 5
        elif sentiment == "mixed":
            trust_score -= 5
        trust_score = max(0, min(100, round(trust_score)))

        if trust_score >= 80:
            trust_label = "HIGHLY TRUSTED"
            trust_color = "green"
        elif trust_score >= 60:
            trust_label = "TRUSTED"
            trust_color = "yellow"
        elif trust_score >= 40:
            trust_label = "MIXED SIGNALS"
            trust_color = "orange"
        else:
            trust_label = "PROCEED WITH CAUTION"
            trust_color = "red"

        return {
            "success": True,
            "property_name": doc.get("name"),
            "landlord_name": landlord.get("name"),
            "landlord_type": landlord.get("type"),
            "trust_score": trust_score,
            "trust_label": trust_label,
            "avg_rating": rating,
            "total_reviews": reviews,
            "response_time_hours": response_time,
            "red_flags": red_flags,
            "green_flags": green_flags,
            "recent_sentiment": sentiment,
            "verified": landlord.get("verified", False),
            "summary": f"{landlord.get('name')} scores {trust_score}/100 for trust. {len(red_flags)} red flags, {len(green_flags)} green flags. Recent sentiment: {sentiment}.",
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool 4: Market Velocity Score ────────────────────────────────────────────
def get_market_velocity(
    property_id: str,
) -> dict[str, Any]:
    """
    Calculate how fast properties like this one lease in Auburn.
    Determines urgency: Sign Now / Decide This Week / Take Your Time.

    Args:
        property_id: The property ID to assess

    Returns:
        Market velocity assessment and urgency recommendation
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        # Velocity signals
        reputation = doc.get("reputation_score", 3.5)
        distance = doc.get("distance_to_campus_miles", 1.0)
        price_tier = doc.get("price_tier", "mid")
        available_date = doc.get("available_date", "2026-08-15")
        total_units = doc.get("total_units", 200)

        # Check if any floor plans are unavailable (already leased)
        floor_plans = doc.get("floor_plans", [])
        unavailable = sum(1 for fp in floor_plans if not fp.get("available", True))
        availability_pressure = unavailable / max(len(floor_plans), 1)

        # Calculate velocity score
        velocity = 50  # baseline

        # High reputation = leases fast
        velocity += (reputation - 3.5) * 15

        # Closer to campus = leases faster
        if distance <= 0.5:
            velocity += 20
        elif distance <= 1.0:
            velocity += 10

        # Smaller community = leases faster (more exclusive)
        if total_units < 200:
            velocity += 15
        elif total_units < 400:
            velocity += 5

        # Availability pressure
        velocity += availability_pressure * 20

        # Luxury tier leases faster due to limited supply
        if price_tier == "luxury":
            velocity += 10

        velocity = max(0, min(100, round(velocity)))

        # Days estimate based on velocity
        if velocity >= 80:
            days_to_lease = "24-72 hours"
            urgency = "SIGN NOW"
            urgency_note = "Properties like this lease within days. Don't wait."
        elif velocity >= 60:
            days_to_lease = "3-7 days"
            urgency = "DECIDE THIS WEEK"
            urgency_note = "High demand. Take a tour within 48 hours if interested."
        elif velocity >= 40:
            days_to_lease = "1-2 weeks"
            urgency = "MODERATE URGENCY"
            urgency_note = "Reasonable time to decide, but don't delay more than a week."
        else:
            days_to_lease = "2-4 weeks"
            urgency = "TAKE YOUR TIME"
            urgency_note = "Lower demand. You have time to compare options carefully."

        return {
            "success": True,
            "property_name": doc.get("name"),
            "velocity_score": velocity,
            "estimated_days_to_lease": days_to_lease,
            "urgency": urgency,
            "urgency_note": urgency_note,
            "signals": {
                "reputation_score": reputation,
                "distance_to_campus": distance,
                "floor_plans_unavailable": unavailable,
                "total_units": total_units,
                "price_tier": price_tier,
            }
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool 5: Generate Final Verdict ───────────────────────────────────────────
def generate_property_verdict(
    property_id: str,
    roommates: int = 1,
    budget_per_person: int = 900,
    has_pet: bool = False,
    priorities: str = "balanced",
) -> dict[str, Any]:
    """
    Generate a final Sign / Negotiate / Pass verdict for a property.
    Synthesizes all analysis into a single recommendation with reasoning.

    Args:
        property_id: The property ID to evaluate
        roommates: Number of roommates
        budget_per_person: Student's budget per person
        has_pet: Whether student has a pet
        priorities: Student's priorities - 'location', 'price', 'amenities', 'balanced'

    Returns:
        Final verdict with score breakdown and one-paragraph reasoning
    """
    try:
        doc = _db.properties.find_one({"property_id": property_id})
        if not doc:
            return {"success": False, "error": f"Property {property_id} not found"}

        landlord = _db.landlords.find_one({"landlord_id": doc.get("landlord_id")})
        floor_plans = doc.get("floor_plans", [])
        fees = doc.get("fees", {})
        amenities = doc.get("amenities", {})

        # Get best floor plan
        best_plan = None
        for fp in floor_plans:
            if fp.get("beds", 1) >= roommates:
                if best_plan is None or fp["rent_per_person"] < best_plan["rent_per_person"]:
                    best_plan = fp
        if not best_plan and floor_plans:
            best_plan = min(floor_plans, key=lambda x: x["rent_per_person"])

        rent = best_plan["rent_per_person"] if best_plan else 0
        utilities = doc.get("utilities_estimate_monthly", 100)
        true_monthly = rent + utilities

        # Score each dimension (0-100)
        scores = {}

        # 1. Value score
        budget_ratio = rent / budget_per_person if budget_per_person else 1
        if budget_ratio <= 0.75:
            scores["value"] = 95
        elif budget_ratio <= 0.90:
            scores["value"] = 80
        elif budget_ratio <= 1.0:
            scores["value"] = 65
        elif budget_ratio <= 1.15:
            scores["value"] = 40
        else:
            scores["value"] = 15

        # 2. Location score
        distance = doc.get("distance_to_campus_miles", 1.5)
        if distance <= 0.2:
            scores["location"] = 100
        elif distance <= 0.5:
            scores["location"] = 85
        elif distance <= 1.0:
            scores["location"] = 65
        elif distance <= 1.5:
            scores["location"] = 45
        else:
            scores["location"] = 25

        # Boost for Tiger Transit
        if doc.get("tiger_transit"):
            scores["location"] = min(100, scores["location"] + 10)

        # 3. Amenities score
        amenity_score = 0
        if amenities.get("pool"): amenity_score += 15
        if amenities.get("gym"): amenity_score += 15
        if amenities.get("study_rooms"): amenity_score += 10
        if amenities.get("furnished"): amenity_score += 15
        if amenities.get("in_unit_laundry"): amenity_score += 20
        if amenities.get("wifi_included"): amenity_score += 10
        if amenities.get("balcony"): amenity_score += 5
        if amenities.get("rooftop"): amenity_score += 10
        if amenities.get("coffee_lounge"): amenity_score += 5
        if amenities.get("game_room"): amenity_score += 5
        scores["amenities"] = min(100, amenity_score)

        # 4. Reputation score
        reputation = doc.get("reputation_score", 3.5)
        scores["reputation"] = round((reputation / 5) * 100)

        # 5. Pet score (if applicable)
        if has_pet:
            if amenities.get("pet_friendly"):
                pet_deposit = fees.get("pet_deposit", 0)
                pet_monthly = fees.get("pet_monthly", 0)
                if pet_deposit <= 200 and pet_monthly <= 40:
                    scores["pet_friendliness"] = 90
                elif pet_deposit <= 400:
                    scores["pet_friendliness"] = 65
                else:
                    scores["pet_friendliness"] = 35
            else:
                scores["pet_friendliness"] = 0

        # Weight by priorities
        weights = {
            "location": {"location": 0.40, "value": 0.20, "amenities": 0.20, "reputation": 0.20},
            "price":    {"value": 0.45, "location": 0.20, "amenities": 0.15, "reputation": 0.20},
            "amenities": {"amenities": 0.40, "location": 0.20, "value": 0.20, "reputation": 0.20},
            "balanced": {"value": 0.25, "location": 0.25, "amenities": 0.25, "reputation": 0.25},
        }.get(priorities, {"value": 0.25, "location": 0.25, "amenities": 0.25, "reputation": 0.25})

        # Calculate weighted total
        total = sum(scores.get(k, 50) * w for k, w in weights.items())
        if has_pet and "pet_friendliness" in scores:
            total = total * 0.85 + scores["pet_friendliness"] * 0.15

        total = round(total)

        # Generate verdict
        if total >= 78:
            verdict = "SIGN"
            verdict_color = "green"
            verdict_note = "Strong across all your priorities. Move quickly."
        elif total >= 60:
            verdict = "NEGOTIATE"
            verdict_color = "yellow"
            verdict_note = "Good option but room to push on price or terms."
        else:
            verdict = "PASS"
            verdict_color = "red"
            verdict_note = "Doesn't score well enough against your priorities."

        # Negotiation suggestions
        negotiate_tips = []
        if scores.get("value", 100) < 70:
            negotiate_tips.append(f"Ask for 1 month free rent — you're paying ${rent - budget_per_person}/mo above budget")
        if fees.get("admin_fee", 0) > 0:
            negotiate_tips.append(f"Waive the ${fees['admin_fee']} admin fee — it's often negotiable")
        if fees.get("pet_deposit", 0) > 200 and has_pet:
            negotiate_tips.append(f"Negotiate pet deposit down from ${fees['pet_deposit']} — market standard is $200")

        return {
            "success": True,
            "property_name": doc.get("name"),
            "property_id": property_id,
            "verdict": verdict,
            "verdict_color": verdict_color,
            "verdict_note": verdict_note,
            "overall_score": total,
            "score_breakdown": scores,
            "priorities_used": priorities,
            "monthly_true_cost": true_monthly,
            "budget_per_person": budget_per_person,
            "budget_fit": "within budget" if rent <= budget_per_person else f"${rent - budget_per_person} over budget",
            "negotiation_tips": negotiate_tips,
            "landlord_name": landlord.get("name") if landlord else "Unknown",
            "landlord_rating": landlord.get("avg_rating") if landlord else None,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Agent Definition ──────────────────────────────────────────────────────────
analyst_agent = Agent(
    model="gemini-2.5-flash",
    name="nestiq_analyst",
    description="Property analysis specialist that calculates true costs, scores properties across multiple dimensions, runs roommate fragility simulations, and generates Sign/Negotiate/Pass verdicts.",
    instruction="""
You are the Nestiq Analyst Agent — a financial and housing analysis specialist for Auburn University students.

You receive property data from the Scout Agent and perform deep analysis. Your job is to be ruthlessly honest — not to sell properties, but to give students the real picture.

For each property you analyze:
1. Use calculate_true_cost to get the full cost picture including utilities and fees
2. Use analyze_roommate_scenarios to show what happens if roommates drop out
3. Use analyze_landlord_reputation to surface red flags and trust signals
4. Use get_market_velocity to assess urgency
5. Use generate_property_verdict to produce the final Sign/Negotiate/Pass verdict

Always lead with the verdict. Students want the answer first, then the reasoning.

Be specific with numbers. Never say "affordable" — say "$725/person including utilities."
Surface negotiation leverage. If a property is over budget, tell the student exactly what to ask for.
Flag fragile roommate situations clearly. A $619/person property sounds great until one roommate leaves and it becomes $826/person.

Your tone is like a smart older sibling who knows real estate — direct, honest, and on the student's side.
""",
    tools=[
        calculate_true_cost,
        analyze_roommate_scenarios,
        analyze_landlord_reputation,
        get_market_velocity,
        generate_property_verdict,
    ],
)

root_agent = analyst_agent