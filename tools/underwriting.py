from typing import Dict, Any


def analyze_deal(property_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Basic real estate underwriting calculator for Nestiq.

    Takes property assumptions and returns investment metrics:
    - NOI
    - Cap rate
    - Monthly cash flow
    - Cash-on-cash return
    - DSCR
    - Buy / Negotiate / Walk Away verdict
    """

    purchase_price = float(property_data["purchase_price"])
    monthly_rent = float(property_data["monthly_rent"])
    vacancy_rate = float(property_data.get("vacancy_rate", 0.05))
    annual_taxes = float(property_data.get("annual_taxes", 0))
    annual_insurance = float(property_data.get("annual_insurance", 0))
    monthly_hoa = float(property_data.get("monthly_hoa", 0))
    annual_repairs = float(property_data.get("annual_repairs", monthly_rent * 12 * 0.08))
    annual_management = float(property_data.get("annual_management", monthly_rent * 12 * 0.08))

    down_payment_pct = float(property_data.get("down_payment_pct", property_data.get("down_payment_percent", 25))) / 100 if float(property_data.get("down_payment_pct", property_data.get("down_payment_percent", 25))) > 1 else float(property_data.get("down_payment_pct", 0.25))
    interest_rate = float(property_data.get("interest_rate", 7)) / 100 if float(property_data.get("interest_rate", 7)) > 1 else float(property_data.get("interest_rate", 0.07))
    loan_term_years = int(property_data.get("loan_term_years", 30))
    closing_costs = float(property_data.get("closing_costs", purchase_price * 0.03))
    repair_budget = float(property_data.get("repair_budget", 0))

    annual_gross_rent = monthly_rent * 12
    vacancy_loss = annual_gross_rent * vacancy_rate
    effective_gross_income = annual_gross_rent - vacancy_loss

    annual_hoa = monthly_hoa * 12
    operating_expenses = annual_taxes + annual_insurance + annual_hoa + annual_repairs + annual_management
    noi = effective_gross_income - operating_expenses

    cap_rate = noi / purchase_price if purchase_price else 0

    loan_amount = purchase_price * (1 - down_payment_pct)
    down_payment = purchase_price * down_payment_pct
    monthly_interest_rate = interest_rate / 12
    number_of_payments = loan_term_years * 12

    if monthly_interest_rate > 0:
        monthly_debt_service = loan_amount * (
            monthly_interest_rate * (1 + monthly_interest_rate) ** number_of_payments
        ) / ((1 + monthly_interest_rate) ** number_of_payments - 1)
    else:
        monthly_debt_service = loan_amount / number_of_payments

    annual_debt_service = monthly_debt_service * 12
    annual_cash_flow = noi - annual_debt_service
    monthly_cash_flow = annual_cash_flow / 12

    total_cash_invested = down_payment + closing_costs + repair_budget
    cash_on_cash_return = annual_cash_flow / total_cash_invested if total_cash_invested else 0
    dscr = noi / annual_debt_service if annual_debt_service else 0

    if dscr >= 1.20 and cash_on_cash_return >= 0.08 and monthly_cash_flow > 0:
        verdict = "BUY"
    elif dscr >= 1.00 and monthly_cash_flow >= 0:
        verdict = "NEGOTIATE"
    else:
        verdict = "WALK AWAY"

    return {
        "property_name": property_data.get("property_name", "Unnamed Property"),
        "purchase_price": round(purchase_price, 2),
        "monthly_rent": round(monthly_rent, 2),
        "noi": round(noi, 2),
        "cap_rate": round(cap_rate, 4),
        "monthly_debt_service": round(monthly_debt_service, 2),
        "monthly_cash_flow": round(monthly_cash_flow, 2),
        "annual_cash_flow": round(annual_cash_flow, 2),
        "cash_on_cash_return": round(cash_on_cash_return, 4),
        "dscr": round(dscr, 2),
        "total_cash_invested": round(total_cash_invested, 2),
        "verdict": verdict,
    }
