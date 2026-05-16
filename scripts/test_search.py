"""Test Vector Search and geospatial queries on seeded Auburn properties."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient
from google import genai

PROJECT_ID = "nestiq-496422"
LOCATION = "us-central1"

client = MongoClient(os.getenv("MONGODB_URI"))
db = client[os.getenv("MONGODB_DATABASE", "nestiq")]
genai_client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

def embed(text):
    result = genai_client.models.embed_content(model="text-embedding-004", contents=text)
    return result.embeddings[0].values

def test_vector_search():
    print("\n🔍 TEST 1: Vector Search — 'quiet place to study walking distance'")
    query_embedding = embed("quiet place to study walking distance to campus")
    results = list(db.properties.aggregate([
        {"$vectorSearch": {
            "index": "nestiq_vector_index",
            "path": "embedding",
            "queryVector": query_embedding,
            "numCandidates": 20,
            "limit": 3
        }},
        {"$project": {"name": 1, "distance_to_campus_miles": 1, "reputation_score": 1, "score": {"$meta": "vectorSearchScore"}}}
    ]))
    for r in results:
        print(f"  {r['name']} — {r['distance_to_campus_miles']}mi — score: {r['score']:.4f}")

def test_geospatial():
    print("\n📍 TEST 2: Geospatial — properties within 0.5 miles of campus center")
    campus = [-85.4808, 32.6099]
    results = list(db.properties.find(
        {"coordinates": {"$nearSphere": {"$geometry": {"type": "Point", "coordinates": campus}, "$maxDistance": 800}}},
        {"name": 1, "distance_to_campus_miles": 1}
    ).limit(5))
    for r in results:
        print(f"  {r['name']} — {r['distance_to_campus_miles']}mi")

def test_filter():
    print("\n🐾 TEST 3: Filter — pet friendly under $800/person")
    results = list(db.properties.find(
        {"amenities.pet_friendly": True, "floor_plans.rent_per_person": {"$lte": 800}},
        {"name": 1, "reputation_score": 1}
    ))
    for r in results:
        print(f"  {r['name']} — rating: {r['reputation_score']}")

def test_landlords():
    print("\n🏢 TEST 4: Landlord reputation data")
    results = list(db.landlords.find({}, {"name": 1, "avg_rating": 1, "red_flags": 1}).sort("avg_rating", -1).limit(3))
    for r in results:
        print(f"  {r['name']} — {r['avg_rating']}★ — flags: {r['red_flags']}")

if __name__ == "__main__":
    print("=" * 50)
    print("  NESTIQ v2 — Database Search Tests")
    print("=" * 50)
    try:
        test_vector_search()
    except Exception as e:
        print(f"  ⚠️  Vector Search not ready yet: {e}")
        print("  Wait 2-3 more minutes and retry.")
    test_geospatial()
    test_filter()
    test_landlords()
    print("\n✅ Tests complete.")
