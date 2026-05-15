from google.adk.agents.llm_agent import Agent

from tools.underwriting import analyze_deal
from tools.mongodb_client import save_underwriting_result


def analyze_real_estate_deal(
    property_name: str,
    purchase_price: float,
    monthly_rent: float,
    annual_taxes: float = 0,
    annual_insurance: float = 0,
    monthly_hoa: float = 0,
    vacancy_rate: float = 0.05,
    annual_repairs: float = 0,
    annual_management: float = 0,
    down_payment_pct: float = 0.25,
    interest_rate: float = 0.07,
    loan_term_years: int = 30,
    closing_costs: float = 0,
    repair_budget: float = 0,
) -> dict:
    """
    Analyze a real estate investment deal and save the result to MongoDB.

    Args:
        property_name: Name or address of the property.
        purchase_price: Total purchase price of the property.
        monthly_rent: Expected monthly rent.
        annual_taxes: Estimated annual property taxes.
        annual_insurance: Estimated annual insurance cost.
        monthly_hoa: Monthly HOA fee, if any.
        vacancy_rate: Expected vacancy rate as a decimal, such as 0.05 for 5%.
        annual_repairs: Estimated annual repair and maintenance cost.
        annual_management: Estimated annual property management cost.
        down_payment_pct: Down payment percentage as a decimal.
        interest_rate: Annual loan interest rate as a decimal.
        loan_term_years: Loan term in years.
        closing_costs: Estimated closing costs.
        repair_budget: Upfront repair or renovation budget.

    Returns:
        A dictionary with underwriting metrics, verdict, and MongoDB save status.
    """

    property_data = {
        "property_name": property_name,
        "purchase_price": purchase_price,
        "monthly_rent": monthly_rent,
        "annual_taxes": annual_taxes,
        "annual_insurance": annual_insurance,
        "monthly_hoa": monthly_hoa,
        "vacancy_rate": vacancy_rate,
        "annual_repairs": annual_repairs,
        "annual_management": annual_management,
        "down_payment_pct": down_payment_pct,
        "interest_rate": interest_rate,
        "loan_term_years": loan_term_years,
        "closing_costs": closing_costs,
        "repair_budget": repair_budget,
    }

    result = analyze_deal(property_data)

    try:
        inserted_id = save_underwriting_result(property_data, result)
        result["mongodb_status"] = "saved"
        result["mongodb_id"] = inserted_id
    except Exception as exc:
        result["mongodb_status"] = "error"
        result["mongodb_error"] = str(exc)

    return {
        "status": "success",
        "message": "Deal analyzed.",
        "analysis": result,
    }


root_agent = Agent(
    model="gemini-2.5-flash",
    name="nestiq_agent",
    description="AI real estate investment underwriting agent for analyzing rental property deals.",
    instruction="""
You are Nestiq, an AI real estate investment analysis agent.

Your job is to help users evaluate rental property deals using underwriting math.
When a user gives a property scenario, use the analyze_real_estate_deal tool.

Always explain:
1. The verdict: BUY, NEGOTIATE, or WALK AWAY
2. NOI
3. Cap rate
4. Monthly cash flow
5. Cash-on-cash return
6. DSCR
7. The biggest risk in the deal
8. What price or assumption would make the deal better

Do not claim this is financial advice. Frame it as educational investment analysis.
""",
    tools=[analyze_real_estate_deal],
)
