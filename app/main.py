
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.underwriting import analyze_deal
from tools.mongodb_client import save_underwriting_result
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