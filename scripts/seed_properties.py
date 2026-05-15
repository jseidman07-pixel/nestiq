"""
Nestiq v2 — Property Seed Script
Loads Auburn properties into MongoDB, generates Vertex AI embeddings,
and creates Vector Search + Geospatial indexes.
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient, GEOSPHERE
from pymongo.operations import SearchIndexModel

load_dotenv()

# ── Google / Vertex AI ──────────────────────────────────────────────────────
from google import genai

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422")
LOCATION   = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# ── MongoDB ─────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGODB_URI")
DB_NAME   = os.getenv("MONGODB_DATABASE", "nestiq")

client = MongoClient(MONGO_URI)
db     = client[DB_NAME]


def generate_embedding(text: str) -> list[float]:
    """Generate a Vertex AI embedding for a text string."""
    result = genai_client.models.embed_content(
        model="text-embedding-004",
        contents=text,
    )
    return result.embeddings[0].values


def build_embedding_text(prop: dict) -> str:
    """Build a rich text representation of a property for embedding."""
    amenity_list = [k.replace("_", " ") for k, v in prop["amenities"].items() if v]
    tag_list     = prop.get("tags", [])
    floor_plans  = prop.get("floor_plans", [])
    price_range  = f"${min(fp['rent_per_person'] for fp in floor_plans)} to ${max(fp['rent_per_person'] for fp in floor_plans)} per person"

    text = f"""
{prop['name']} is a {prop['price_tier']} student apartment in Auburn Alabama.
Located {prop['distance_to_campus_miles']} miles from Auburn University campus,
{prop['walk_time_minutes']} minute walk or {prop['drive_time_minutes']} minute drive.
Rent ranges from {price_range} per month.
Description: {prop['description']}
Amenities include: {', '.join(amenity_list)}.
Tags: {', '.join(tag_list)}.
Tiger Transit access: {'yes' if prop['tiger_transit'] else 'no'}.
Reputation score: {prop['reputation_score']} out of 5.
Price tier: {prop['price_tier']}.
""".strip()
    return text


def seed_properties():
    """Load properties from JSON, embed them, and insert into MongoDB."""
    seed_path = Path("data/seed/auburn_properties.json")
    if not seed_path.exists():
        print(f"ERROR: Seed file not found at {seed_path}")
        sys.exit(1)

    with open(seed_path) as f:
        properties = json.load(f)

    collection = db["properties"]

    # Drop existing data for a clean reseed
    collection.drop()
    print(f"Dropped existing properties collection.")

    print(f"\nSeeding {len(properties)} Auburn properties...\n")

    for i, prop in enumerate(properties):
        print(f"[{i+1}/{len(properties)}] Processing: {prop['name']}")

        # Generate embedding from rich text description
        embedding_text = build_embedding_text(prop)
        print(f"  → Generating Vertex AI embedding...")
        embedding = generate_embedding(embedding_text)
        prop["embedding"] = embedding
        prop["embedding_text"] = embedding_text

        # Insert into MongoDB
        result = collection.insert_one(prop)
        print(f"  → Inserted with ID: {result.inserted_id}")
        print(f"  → Embedding dimensions: {len(embedding)}")

        # Small delay to avoid rate limiting
        if i < len(properties) - 1:
            time.sleep(0.5)

    print(f"\n✅ All {len(properties)} properties seeded successfully.\n")
    return collection


def create_geospatial_index(collection):
    """Create a 2dsphere geospatial index on coordinates."""
    print("Creating geospatial index...")
    collection.create_index([("coordinates", GEOSPHERE)])
    print("✅ Geospatial index created on 'coordinates' field.")


def create_vector_search_index(collection):
    """Create Atlas Vector Search index for semantic property search."""
    print("\nCreating Vector Search index...")
    print("NOTE: Vector Search index creation is async in Atlas.")
    print("It may take 1-3 minutes to become active after this script finishes.")

    index_definition = {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": 768,
                "similarity": "cosine"
            },
            {
                "type": "filter",
                "path": "amenities.pet_friendly"
            },
            {
                "type": "filter",
                "path": "amenities.furnished"
            },
            {
                "type": "filter",
                "path": "amenities.pool"
            },
            {
                "type": "filter",
                "path": "amenities.gym"
            },
            {
                "type": "filter",
                "path": "tiger_transit"
            },
            {
                "type": "filter",
                "path": "price_tier"
            }
        ]
    }

    search_index = SearchIndexModel(
        definition=index_definition,
        name="nestiq_vector_index",
        type="vectorSearch"
    )

    try:
        collection.create_search_index(search_index)
        print("✅ Vector Search index 'nestiq_vector_index' creation initiated.")
    except Exception as e:
        if "already exists" in str(e).lower():
            print("ℹ️  Vector Search index already exists — skipping.")
        else:
            print(f"⚠️  Vector Search index error: {e}")
            print("    You may need to create it manually in the Atlas UI.")


def create_regular_indexes(collection):
    """Create standard MongoDB indexes for common queries."""
    print("\nCreating standard indexes...")
    collection.create_index("property_id", unique=True)
    collection.create_index("price_tier")
    collection.create_index("distance_to_campus_miles")
    collection.create_index("reputation_score")
    collection.create_index("landlord_id")
    collection.create_index([("floor_plans.rent_per_person", 1)])
    print("✅ Standard indexes created.")


def seed_landlords():
    """Seed landlord reputation data."""
    print("\nSeeding landlord reputation data...")

    landlords = [
        {
            "landlord_id": "landlord_yugo",
            "name": "Yugo Student Living",
            "type": "corporate",
            "avg_rating": 4.2,
            "total_reviews": 847,
            "response_time_hours": 4,
            "maintenance_rating": 4.0,
            "communication_rating": 4.3,
            "red_flags": [],
            "green_flags": ["fast maintenance", "professional management", "pet friendly"],
            "recent_sentiment": "positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_grove",
            "name": "The Grove at Auburn Management",
            "type": "corporate",
            "avg_rating": 4.7,
            "total_reviews": 1203,
            "response_time_hours": 2,
            "maintenance_rating": 4.6,
            "communication_rating": 4.8,
            "red_flags": [],
            "green_flags": ["best management in Auburn", "quick responses", "community events", "always clean"],
            "recent_sentiment": "very positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_oliv",
            "name": "ōLiv Auburn Management",
            "type": "corporate",
            "avg_rating": 4.4,
            "total_reviews": 412,
            "response_time_hours": 6,
            "maintenance_rating": 4.2,
            "communication_rating": 4.5,
            "red_flags": ["high admin fees", "strict guest policy"],
            "green_flags": ["luxury amenities", "mental health support", "great location"],
            "recent_sentiment": "positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_magnolia",
            "name": "The Magnolia Auburn LLC",
            "type": "corporate",
            "avg_rating": 4.1,
            "total_reviews": 389,
            "response_time_hours": 8,
            "maintenance_rating": 4.0,
            "communication_rating": 4.2,
            "red_flags": ["$100 admin fee", "slow maintenance on weekends"],
            "green_flags": ["wifi included", "fair pricing", "good location"],
            "recent_sentiment": "positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_logan",
            "name": "Logan Square Properties",
            "type": "corporate",
            "avg_rating": 3.9,
            "total_reviews": 276,
            "response_time_hours": 12,
            "maintenance_rating": 3.7,
            "communication_rating": 4.0,
            "red_flags": ["maintenance delays reported", "parking issues"],
            "green_flags": ["nice finishes", "balconies", "flexible leases"],
            "recent_sentiment": "mixed",
            "verified": True
        },
        {
            "landlord_id": "landlord_shelton",
            "name": "Shelton Mill Properties LLC",
            "type": "corporate",
            "avg_rating": 4.0,
            "total_reviews": 198,
            "response_time_hours": 10,
            "maintenance_rating": 3.9,
            "communication_rating": 4.1,
            "red_flags": [],
            "green_flags": ["tiger transit access", "recently renovated", "spacious units"],
            "recent_sentiment": "positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_1322",
            "name": "1322 North Management",
            "type": "corporate",
            "avg_rating": 4.5,
            "total_reviews": 167,
            "response_time_hours": 3,
            "maintenance_rating": 4.4,
            "communication_rating": 4.6,
            "red_flags": ["no pets allowed", "strict noise policy"],
            "green_flags": ["excellent management", "well maintained", "premium finishes"],
            "recent_sentiment": "very positive",
            "verified": True
        },
        {
            "landlord_id": "landlord_lakewood",
            "name": "Lakewood Commons LLC",
            "type": "small_landlord",
            "avg_rating": 3.6,
            "total_reviews": 89,
            "response_time_hours": 24,
            "maintenance_rating": 3.4,
            "communication_rating": 3.8,
            "red_flags": ["slow maintenance response", "older building"],
            "green_flags": ["lowest price in Auburn", "flexible leases", "pet friendly"],
            "recent_sentiment": "mixed",
            "verified": False
        }
    ]

    collection = db["landlords"]
    collection.drop()

    for landlord in landlords:
        collection.insert_one(landlord)

    collection.create_index("landlord_id", unique=True)
    print(f"✅ {len(landlords)} landlords seeded.")


def seed_user_sessions():
    """Create the user_sessions collection with indexes."""
    print("\nSetting up user_sessions collection...")
    collection = db["user_sessions"]
    collection.create_index("user_id", unique=True)
    collection.create_index("last_active")
    print("✅ user_sessions collection ready.")


def main():
    print("=" * 60)
    print("  NESTIQ v2 — Property Database Seed Script")
    print("=" * 60)

    # Verify MongoDB connection
    try:
        client.admin.command("ping")
        print("✅ MongoDB connection verified.\n")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        sys.exit(1)

    # Run all seeding steps
    collection = seed_properties()
    create_geospatial_index(collection)
    create_vector_search_index(collection)
    create_regular_indexes(collection)
    seed_landlords()
    seed_user_sessions()

    print("\n" + "=" * 60)
    print("  ✅ Nestiq v2 database ready.")
    print("  ⏳ Wait 2-3 minutes for Vector Search index to activate.")
    print("  Then run: python -m scripts.test_search")
    print("=" * 60)


if __name__ == "__main__":
    main()