import json
from pathlib import Path

from tools.underwriting import analyze_deal
from tools.mongodb_client import save_underwriting_result


def main():
    data_path = Path("data/sample_properties.json")
    properties = json.loads(data_path.read_text())

    print("Saving sample underwriting results to MongoDB...")

    for property_data in properties:
        result = analyze_deal(property_data)
        inserted_id = save_underwriting_result(property_data, result)

        print("\nSaved deal:")
        print(f"Property: {result['property_name']}")
        print(f"Verdict: {result['verdict']}")
        print(f"MongoDB ID: {inserted_id}")

    print("\nDone. MongoDB persistence is working.")


if __name__ == "__main__":
    main()
