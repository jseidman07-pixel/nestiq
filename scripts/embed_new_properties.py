"""
Nestiq Embedding Generator for Newly Discovered Properties

Run:
python -m scripts.embed_new_properties
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai

load_dotenv(".env")

db = MongoClient(os.getenv("MONGODB_URI"))[os.getenv("MONGODB_DATABASE", "nestiq")]

genai_client = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_list(items):
    if not items:
        return "none listed"
    if isinstance(items, list):
        return ", ".join(str(x) for x in items if x)
    return str(items)


def build_embedding_text(prop):
    amenities = clean_list(prop.get("amenities"))
    tags = clean_list(prop.get("tags"))
    bedrooms = clean_list(prop.get("bedrooms_available"))
    floor_plans = prop.get("floor_plans") or []

    floor_plan_text = []
    for fp in floor_plans[:8]:
        floor_plan_text.append(
            f"{fp.get('name')} {fp.get('beds')} bed {fp.get('baths')} bath rent {fp.get('rent_text') or fp.get('rent')}"
        )

    return f"""
{prop.get('name')} is a housing property near Auburn University.

Category: {prop.get('housing_category') or prop.get('price_tier') or 'unknown'}.
Address: {prop.get('address')}.
Distance to campus: {prop.get('distance_to_campus_miles')} miles.
Walk time: {prop.get('walk_time_minutes')} minutes.
Drive time: {prop.get('drive_time_minutes')} minutes.

Rent range: {prop.get('rent_min')} to {prop.get('rent_max')} per month when available.
Rent notes: {prop.get('rent_notes')}.
Availability status: {prop.get('availability_status')}.
Available date: {prop.get('available_date')}.

Description: {prop.get('description')}

Bedroom options: {bedrooms}.
Floor plans: {clean_list(floor_plan_text)}.
Amenities: {amenities}.
Tags: {tags}.
Move-in specials: {clean_list(prop.get('move_in_specials'))}.
Lease terms: {clean_list(prop.get('lease_terms'))}.
Utilities included: {clean_list(prop.get('utilities_included_list'))}.
Pet policy: {prop.get('pet_policy_text')}.
Parking info: {prop.get('parking_info')}.

Google rating: {prop.get('google_rating')} from {prop.get('google_review_count')} reviews.
Reputation score: {prop.get('reputation_score')}.
Tiger Transit: {prop.get('tiger_transit')}.
Status: {prop.get('status')}.
Enrichment status: {prop.get('enrichment_status')}.
""".strip()


def generate_embedding(text):
    result = genai_client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    return result.embeddings[0].values


def main():
    props = list(db.properties.find({
        "$or": [
            {"embedding_needed": True},
            {"embedding": {"$exists": False}},
            {"embedding": None},
        ]
    }))

    print("\n" + "=" * 70)
    print("  NESTIQ — Generate Embeddings for New Properties")
    print("=" * 70)
    print(f"Found {len(props)} properties needing embeddings.\n")

    updated = 0
    errors = []

    for i, prop in enumerate(props, 1):
        name = prop.get("name")
        pid = prop.get("property_id")

        print(f"[{i}/{len(props)}] {name}")

        try:
            embedding_text = build_embedding_text(prop)
            embedding = generate_embedding(embedding_text)

            db.properties.update_one(
                {"property_id": pid},
                {"$set": {
                    "embedding_text": embedding_text,
                    "embedding": embedding,
                    "embedding_needed": False,
                    "embedding_model": "text-embedding-004",
                    "embedding_generated_at": now_iso(),
                }}
            )

            print(f"  ✅ Embedded. Dimensions: {len(embedding)}")
            updated += 1

        except Exception as e:
            msg = f"{name}: {e}"
            errors.append(msg)
            print(f"  ✗ Error: {e}")

    print("\n" + "=" * 70)
    print("  ✅ Embedding run complete.")
    print(f"  Updated: {updated}")
    print(f"  Errors: {len(errors)}")
    print("=" * 70)

    if errors:
        print("\nErrors:")
        for e in errors:
            print(" -", e)


if __name__ == "__main__":
    main()
