import json
from pathlib import Path

from tools.underwriting import analyze_deal


def main():
    data_path = Path("data/sample_properties.json")
    properties = json.loads(data_path.read_text())

    for property_data in properties:
        result = analyze_deal(property_data)

        print("\n" + "=" * 60)
        print(result["property_name"])
        print("=" * 60)
        print(f"Purchase Price: ${result['purchase_price']:,.0f}")
        print(f"Monthly Rent: ${result['monthly_rent']:,.0f}")
        print(f"NOI: ${result['noi']:,.0f}")
        print(f"Cap Rate: {result['cap_rate'] * 100:.2f}%")
        print(f"Monthly Debt Service: ${result['monthly_debt_service']:,.0f}")
        print(f"Monthly Cash Flow: ${result['monthly_cash_flow']:,.0f}")
        print(f"Cash-on-Cash Return: {result['cash_on_cash_return'] * 100:.2f}%")
        print(f"DSCR: {result['dscr']}")
        print(f"Verdict: {result['verdict']}")


if __name__ == "__main__":
    main()
