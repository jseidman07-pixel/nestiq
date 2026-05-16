"""
Nestiq Autonomous Review Collector
Pulls real Google Places reviews for all Auburn properties.
Filters to past 2 years only — older reviews may be outdated.
Run: python -m scripts.collect_reviews
"""

import os
import json
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai
from google.genai import types

load_dotenv()

_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
PLACES_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

_genai = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

# Two years ago in Unix timestamp
TWO_YEARS_AGO = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


def search_place(property_name: str) -> dict | None:
    """Find a property on Google Places and return place_id, rating, total reviews."""
    query = urllib.parse.quote(f"{property_name} Auburn Alabama student apartments")
    url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={query}&key={PLACES_KEY}"
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        if data.get("status") == "OK" and data.get("results"):
            result = data["results"][0]
            return {
                "place_id": result.get("place_id"),
                "google_rating": result.get("rating"),
                "google_review_count": result.get("user_ratings_total", 0),
                "google_name": result.get("name"),
            }
    except Exception as e:
        print(f"  Search error: {e}")
    return None


def get_place_reviews(place_id: str) -> list[dict]:
    """
    Fetch up to 5 most recent Google reviews for a place.
    Google Places API free tier returns max 5 reviews sorted by relevance.
    We request sort by newest to maximize recency.
    """
    url = (
        f"https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}"
        f"&fields=name,rating,reviews,user_ratings_total"
        f"&reviews_sort=newest"
        f"&key={PLACES_KEY}"
    )
    try:
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        if data.get("status") == "OK":
            return data.get("result", {}).get("reviews", [])
    except Exception as e:
        print(f"  Reviews fetch error: {e}")
    return []


def analyze_sentiment(text: str, property_name: str) -> dict:
    """Use Gemini to analyze sentiment and extract key themes from a review."""
    prompt = f"""Analyze this student review of {property_name} apartments in Auburn, Alabama.

Review: "{text}"

Respond ONLY with valid JSON:
{{
  "sentiment": "positive" or "negative" or "mixed",
  "themes": ["list", "of", "2-4", "key", "topics"],
  "red_flags": ["specific problems mentioned, empty list if none"],
  "green_flags": ["specific positives mentioned, empty list if none"],
  "summary": "one sentence plain English summary"
}}"""

    try:
        response = _genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_text(text=prompt)],
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:-1])
        return json.loads(raw)
    except Exception as e:
        # Fallback: simple sentiment based on rating
        return {
            "sentiment": "positive" if "positive" in text.lower() else "negative",
            "themes": ["general experience"],
            "red_flags": [],
            "green_flags": [],
            "summary": text[:100],
        }


def collect_reviews_for_property(property_doc: dict) -> int:
    """Collect and store Google reviews for one property. Returns count added."""
    pid = property_doc["property_id"]
    name = property_doc["name"]

    print(f"\n  Searching Google Places for: {name}")
    place = search_place(name)
    if not place:
        print(f"  ✗ Not found on Google Places")
        return 0

    print(f"  ✓ Found: {place['google_name']} — {place['google_rating']}★ ({place['google_review_count']} total reviews)")

    # Update property document with Google Places data
    _db.properties.update_one(
        {"property_id": pid},
        {"$set": {
            "google_place_id": place["place_id"],
            "google_rating": place["google_rating"],
            "google_review_count": place["google_review_count"],
        }}
    )

    reviews = get_place_reviews(place["place_id"])
    if not reviews:
        print(f"  No reviews returned")
        return 0

    added = 0
    for review in reviews:
        # Filter to past 2 years only
        review_time = review.get("time", 0)
        if review_time < TWO_YEARS_AGO:
            print(f"  Skipping old review from {review.get('relative_time_description', 'unknown date')}")
            continue

        # Skip very short reviews — not useful
        text = review.get("text", "").strip()
        if len(text) < 30:
            continue

        # Check for duplicate
        existing = _db.property_reviews.find_one({
            "property_id": pid,
            "source": "Google Reviews",
            "author": review.get("author_name"),
            "date": datetime.fromtimestamp(review_time).strftime("%Y-%m-%d"),
        })
        if existing:
            continue

        # Analyze with Gemini
        print(f"  Analyzing review by {review.get('author_name')} ({review.get('relative_time_description')})...")
        analysis = analyze_sentiment(text, name)
        time.sleep(0.5)  # Rate limit

        doc = {
            "property_id": pid,
            "property_name": name,
            "source": "Google Reviews",
            "author": review.get("author_name", "Anonymous"),
            "date": datetime.fromtimestamp(review_time).strftime("%Y-%m-%d"),
            "rating": review.get("rating", 3),
            "text": text,
            "relative_time": review.get("relative_time_description"),
            "sentiment": analysis.get("sentiment", "mixed"),
            "themes": analysis.get("themes", []),
            "red_flags": analysis.get("red_flags", []),
            "green_flags": analysis.get("green_flags", []),
            "summary": analysis.get("summary", ""),
            "collected_at": datetime.utcnow().isoformat(),
            "verified": True,
            "auto_collected": True,
        }

        _db.property_reviews.insert_one(doc)
        added += 1
        print(f"  ✓ Added: {analysis['sentiment']} review ({review.get('rating')}★)")

    return added


def update_property_summary(property_id: str, property_name: str):
    """Recalculate and update the review summary for a property."""
    from collections import Counter

    reviews = list(_db.property_reviews.find({"property_id": property_id}))
    if not reviews:
        return

    total = len(reviews)
    positive = sum(1 for r in reviews if r.get("sentiment") == "positive")
    negative = sum(1 for r in reviews if r.get("sentiment") == "negative")
    avg_rating = round(sum(r.get("rating", 3) for r in reviews) / total, 1)
    sentiment_pct = round((positive / total) * 100)
    overall = "positive" if avg_rating >= 4.0 else "mixed" if avg_rating >= 3.0 else "negative"

    all_red = [f for r in reviews for f in r.get("red_flags", [])]
    all_green = [f for r in reviews for f in r.get("green_flags", [])]
    top_red = [f for f, _ in Counter(all_red).most_common(5)]
    top_green = [f for f, _ in Counter(all_green).most_common(5)]

    _db.property_review_summaries.update_one(
        {"property_id": property_id},
        {"$set": {
            "property_id": property_id,
            "property_name": property_name,
            "overall": overall,
            "avg_rating": avg_rating,
            "sentiment_score": sentiment_pct,
            "count": total,
            "positive_count": positive,
            "negative_count": negative,
            "top_red_flags": top_red,
            "top_green_flags": top_green,
            "updated_at": datetime.utcnow().isoformat(),
        }},
        upsert=True,
    )


def collect_all_reviews():
    print("\n" + "="*60)
    print("  NESTIQ — Autonomous Review Collector")
    print(f"  Collecting reviews from Jan 2024 onwards only")
    print("="*60)

    if not PLACES_KEY:
        print("ERROR: GOOGLE_PLACES_API_KEY not found in .env")
        return

    properties = list(_db.properties.find({}, {"property_id": 1, "name": 1}))
    print(f"\nFound {len(properties)} properties to process.")

    total_added = 0
    for i, prop in enumerate(properties):
        print(f"\n[{i+1}/{len(properties)}] {prop['name']}")
        added = collect_reviews_for_property(prop)
        if added > 0:
            update_property_summary(prop["property_id"], prop["name"])
            total_added += added
        time.sleep(1)  # Be nice to the API

    print("\n" + "="*60)
    print(f"  ✅ Collection complete. Added {total_added} new reviews.")
    print(f"  Total reviews in database: {_db.property_reviews.count_documents({})}")
    print("="*60)


if __name__ == "__main__":
    collect_all_reviews()
