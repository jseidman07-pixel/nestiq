
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import base64
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.underwriting import analyze_deal
from tools.mongodb_client import save_underwriting_result
from tools.lease.scanner import analyze_lease_pdf, get_lease_history
from tools.deal_history import (
    list_recent_saved_deals,
    find_saved_deals_by_verdict,
    get_best_saved_deal,
)

app = FastAPI(
    title="Nestiq API",
    description="AI-powered real estate investment analysis agent",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/ui")
def serve_ui():
    return FileResponse("app/static/index.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class DealRequest(BaseModel):
    property_name: str
    purchase_price: float
    monthly_rent: float
    annual_taxes: float
    annual_insurance: float
    annual_hoa: Optional[float] = 0
    repair_budget: Optional[float] = 0
    closing_costs: Optional[float] = 0
    interest_rate: float
    down_payment_percent: float
    loan_term_years: Optional[int] = 30
    vacancy_rate: Optional[float] = 0.05
    management_fee_rate: Optional[float] = 0.0


@app.get("/")
def root():
    return {"status": "Nestiq is running", "version": "1.0.0"}


@app.post("/analyze-deal")
def analyze_deal_endpoint(request: DealRequest):
    property_data = request.model_dump()
    result = analyze_deal(property_data)
    save_underwriting_result(property_data, result)
    return {
        "property_name": request.property_name,
        "verdict": result["verdict"],
        "metrics": result,
    }


@app.get("/deals/recent")
def recent_deals(limit: int = 5):
    deals = list_recent_saved_deals(limit=limit)
    return {"deals": deals, "count": len(deals)}


@app.get("/deals/verdict/{verdict}")
def deals_by_verdict(verdict: str, limit: int = 10):
    deals = find_saved_deals_by_verdict(verdict=verdict, limit=limit)
    return {"verdict": verdict.upper(), "deals": deals, "count": len(deals)}


@app.get("/deals/best")
def best_deal(metric: str = "cash_on_cash_return"):
    deal = get_best_saved_deal(metric=metric)
    return {"metric": metric, "best_deal": deal}

@app.post("/scan-lease")
async def scan_lease(file: UploadFile = File(...)):
    """
    Upload and analyze a student lease PDF.
    Returns lease red flags, risky clauses, and a plain-English summary.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    contents = await file.read()
    pdf_base64 = base64.b64encode(contents).decode("utf-8")

    result = analyze_lease_pdf(
        pdf_base64=pdf_base64,
        filename=file.filename,
    )

    return result


@app.get("/lease-history")
def lease_history():
    """
    Return saved lease scan history from MongoDB.
    """
    return get_lease_history()


class ChatRequest(BaseModel):
    message: str
    user_id: str = "default_user"

@app.post("/chat")
async def chat(request: ChatRequest):
    from agents.scout.agent import search_properties_by_filters, search_properties_by_description, search_properties_near_campus
    import re
    msg = request.message.lower()

    # Direct property-name search.
    # This lets users ask about places like "191 College" or "Uncommon Auburn"
    # without getting blocked by budget/floor-plan filters.
    import os
    from dotenv import load_dotenv
    from pymongo import MongoClient

    load_dotenv(".env")
    db = MongoClient(os.getenv("MONGODB_URI"))[os.getenv("MONGODB_DATABASE", "nestiq")]

    all_names = list(db.properties.find({}, {"_id": 0, "name": 1}))
    mentioned_names = [
        item["name"]
        for item in all_names
        if item.get("name") and item["name"].lower() in msg
    ]

    if mentioned_names:
        docs = list(db.properties.find(
            {"name": {"$in": mentioned_names}},
            {"_id": 0}
        ).limit(8))

        props = []
        for doc in docs:
            rent = doc.get("rent_per_person") or doc.get("rent_min")

            if not rent and doc.get("floor_plans"):
                rents = []
                for fp in doc.get("floor_plans", []):
                    if isinstance(fp, dict):
                        val = fp.get("rent_per_person") or fp.get("rent")
                        if isinstance(val, (int, float)):
                            rents.append(val)
                rent = min(rents) if rents else None

            props.append({
                "property_id": doc.get("property_id"),
                "name": doc.get("name"),
                "address": doc.get("address"),
                "rent_per_person": rent,
                "rent_min": doc.get("rent_min"),
                "rent_max": doc.get("rent_max"),
                "distance_to_campus_miles": doc.get("distance_to_campus_miles"),
                "reputation_score": doc.get("reputation_score") or doc.get("google_rating"),
                "google_rating": doc.get("google_rating"),
                "google_review_count": doc.get("google_review_count"),
                "amenities": doc.get("amenities", []),
                "tags": doc.get("tags", []),
                "description": doc.get("description"),
                "website": doc.get("website"),
                "housing_category": doc.get("housing_category"),
                "status": doc.get("status"),
                "enrichment_status": doc.get("enrichment_status"),
            })

        lines = [f"Found **{len(props)} mentioned properties** in Nestiq:\n"]
        for p in props:
            rent_text = f"${p['rent_per_person']}/person" if p.get("rent_per_person") else "rent not fully enriched yet"
            distance_text = f"{p.get('distance_to_campus_miles')}mi" if p.get("distance_to_campus_miles") is not None else "distance unknown"
            rating_text = f"{p.get('reputation_score')}★" if p.get("reputation_score") is not None else "rating unknown"
            lines.append(f"**{p['name']}** — {rent_text} · {distance_text} · {rating_text}")

        lines.append("\nClick any property card to see the full analysis.")
        return {"response": "\n".join(lines), "properties": props[:6]}

    budget_match = re.search(r"\$?(\d{3,4})", request.message)
    budget = int(budget_match.group(1)) if budget_match else 2000
    roommate_match = re.search(r"(\d+)\s*(roommate|friend|person|people)", msg)
    roommates = int(roommate_match.group(1)) + 1 if roommate_match else 1
    pet = any(w in msg for w in ["pet", "dog", "cat"])
    furnished = "furnish" in msg
    walking = any(w in msg for w in ["walk", "walking distance"])
    if walking:
        result = search_properties_near_campus(max_walk_minutes=15, roommates=roommates, max_rent_per_person=budget)
    elif any(w in msg for w in ["cozy", "quiet", "vibe", "luxury", "premium"]):
        result = search_properties_by_description(query=request.message, roommates=roommates, max_rent_per_person=budget, pet_friendly=pet, furnished=furnished)
    else:
        result = search_properties_by_filters(roommates=roommates, max_rent_per_person=budget, pet_friendly=pet, furnished=furnished)
    props = result.get("properties", [])
    if not props:
        response_text = "No properties matched. Try increasing your budget or relaxing filters."
    else:
        lines = [f"Found **{len(props)} properties** matching your criteria:\n"]
        for p in props[:4]:
            rent = p.get("rent_per_person")
            rent_text = f"${rent}/person" if rent is not None else "rent not fully enriched yet"
            distance = p.get("distance_to_campus_miles")
            distance_text = f"{distance}mi" if distance is not None else "distance unknown"
            rating = p.get("reputation_score")
            rating_text = f"{rating}★" if rating is not None else "rating unknown"
            lines.append(f"**{p.get('name')}** — {rent_text} · {distance_text} · {rating_text}")
        lines.append("\nClick any property card to see the full analysis.")
        response_text = "\n".join(lines)
    return {"response": response_text, "properties": props[:6]}

@app.get("/analyze/verdict")
def analyze_verdict(property_id: str, roommates: int = 2, budget: int = 800, priorities: str = "balanced"):
    from agents.analyst.agent import generate_property_verdict
    return generate_property_verdict(property_id=property_id, roommates=roommates, budget_per_person=budget, priorities=priorities)

@app.get("/analyze/cost")
def analyze_cost(property_id: str, roommates: int = 2, has_pet: bool = False):
    from agents.analyst.agent import calculate_true_cost
    return calculate_true_cost(property_id=property_id, roommates=roommates, has_pet=has_pet)

@app.get("/analyze/roommates")
def analyze_roommates(property_id: str, planned_roommates: int = 2):
    from agents.analyst.agent import analyze_roommate_scenarios
    return analyze_roommate_scenarios(property_id=property_id, planned_roommates=planned_roommates)

@app.get("/analyze/reputation")
def analyze_reputation(property_id: str):
    from agents.analyst.agent import analyze_landlord_reputation
    return analyze_landlord_reputation(property_id=property_id)


@app.get("/reviews/{property_id}")
def get_property_reviews(property_id: str):
    from pymongo import MongoClient
    import os
    mongo = MongoClient(os.getenv("MONGODB_URI"))
    db = mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
    reviews = list(db.property_reviews.find({"property_id": property_id}, {"_id": 0}).sort("date", -1).limit(10))
    summary = db.property_review_summaries.find_one({"property_id": property_id}, {"_id": 0})
    return {"property_id": property_id, "summary": summary, "reviews": reviews, "count": len(reviews)}