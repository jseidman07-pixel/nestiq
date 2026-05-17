"""
Nestiq Autonomous Auburn Property Discovery Agent
Finds additional off-campus housing near Auburn University using Google Places,
classifies relevance with Gemini, and saves candidates to MongoDB.

Run:
python -m scripts.discover_auburn_properties
"""

import os
import re
import json
import time
import math
import urllib.request
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from pymongo import MongoClient
from google import genai
from google.genai import types

load_dotenv(".env")

_mongo = MongoClient(os.getenv("MONGODB_URI"))
_db = _mongo[os.getenv("MONGODB_DATABASE", "nestiq")]
PLACES_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

_genai = genai.Client(
    vertexai=True,
    project=os.getenv("GOOGLE_CLOUD_PROJECT", "nestiq-496422"),
    location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
)

UNIVERSITY_NAME = "Auburn University"
UNIVERSITY_ID = "auburn_university"

SEARCH_QUERIES = [
    "student apartments near Auburn University",
    "off campus housing near Auburn University",
    "apartments near Auburn University",
    "townhomes near Auburn University",
    "student housing Auburn Alabama",
    "apartment rentals Auburn Alabama near campus",
    "college apartments Auburn Alabama",
    "cottages near Auburn University",
]

MAX_DISTANCE_MILES = 5.0


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:60]


def haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return round(2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)


def google_text_search(query: str, pagetoken: str | None = None) -> dict:
    if pagetoken:
        url = (
            "https://maps.googleapis.com/maps/api/place/textsearch/json"
            f"?pagetoken={pagetoken}&key={PLACES_KEY}"
        )
    else:
        q = urllib.parse.quote(query)
        url = (
            "https://maps.googleapis.com/maps/api/place/textsearch/json"
            f"?query={q}&key={PLACES_KEY}"
        )

    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read())


def get_place_details(place_id: str) -> dict:
    fields = urllib.parse.quote(
        "name,place_id,formatted_address,geometry,website,formatted_phone_number,"
        "rating,user_ratings_total,business_status,types,url"
    )
    url = (
        "https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={place_id}&fields={fields}&key={PLACES_KEY}"
    )

    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())

        if data.get("status") == "OK":
            return data.get("result", {})
    except Exception as e:
        print(f"    Details error: {e}")

    return {}


def find_auburn_campus() -> dict:
    data = google_text_search("Auburn University Auburn Alabama")
    if data.get("status") == "OK" and data.get("results"):
        result = data["results"][0]
        loc = result.get("geometry", {}).get("location", {})
        return {
            "name": result.get("name", UNIVERSITY_NAME),
            "address": result.get("formatted_address"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
        }

    # Fallback if Google Places has a moment.
    return {
        "name": UNIVERSITY_NAME,
        "address": "Auburn, AL",
        "lat": 32.6034,
        "lng": -85.4863,
    }


def parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("```"))

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]

    return json.loads(raw)


def classify_candidate_with_gemini(candidate: dict) -> dict:
    prompt = f"""
You are classifying whether a Google Places result is relevant off-campus student housing for Auburn University students.

Candidate:
{json.dumps(candidate, indent=2)}

Return ONLY valid JSON:
{{
  "is_student_housing": true or false,
  "confidence_score": number between 0 and 1,
  "housing_type": "student apartment, apartment, townhome, cottage, property manager, dorm, hotel, unrelated, or unknown",
  "reason": "one short explanation",
  "likely_student_relevant_features": ["features that suggest student relevance"],
  "red_flags": ["reasons this may not be a real housing property"],
  "recommended_action": "save_candidate, ignore, or needs_review"
}}

Rules:
- Student apartments, off-campus apartments, townhomes, cottages, and student-focused housing near Auburn should usually be true.
- Hotels, dorms, university buildings, random businesses, real estate broker offices, and generic property managers without a specific apartment community should usually be false or needs_review.
- If unsure, use needs_review.
"""

    try:
        response = _genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_text(text=prompt)],
        )
        return parse_json_response(response.text)
    except Exception as e:
        return {
            "is_student_housing": False,
            "confidence_score": 0,
            "housing_type": "unknown",
            "reason": f"Gemini classification failed: {e}",
            "likely_student_relevant_features": [],
            "red_flags": ["classification_failed"],
            "recommended_action": "needs_review",
        }


def already_known(place_id: str | None, name: str) -> bool:
    if place_id:
        existing_property = _db.properties.find_one({"google_place_id": place_id})
        existing_candidate = _db.property_candidates.find_one({"google_place_id": place_id})
        if existing_property or existing_candidate:
            return True

    normalized = slugify(name)
    existing_by_slug = _db.properties.find_one({
        "$or": [
            {"normalized_name": normalized},
            {"discovery_slug": normalized},
        ]
    })
    existing_candidate_by_slug = _db.property_candidates.find_one({
        "discovery_slug": normalized,
        "university_id": UNIVERSITY_ID,
    })

    return bool(existing_by_slug or existing_candidate_by_slug)


def save_candidate(candidate: dict, classification: dict):
    name = candidate.get("name", "Unknown Property")
    place_id = candidate.get("place_id")
    discovery_slug = slugify(name)

    doc = {
        "candidate_id": f"candidate_{UNIVERSITY_ID}_{discovery_slug}",
        "property_name": name,
        "discovery_slug": discovery_slug,
        "university_id": UNIVERSITY_ID,
        "university_name": UNIVERSITY_NAME,
        "source": "google_places_discovery",
        "status": "candidate",
        "google_place_id": place_id,
        "address": candidate.get("formatted_address"),
        "website": candidate.get("website"),
        "phone": candidate.get("formatted_phone_number"),
        "google_rating": candidate.get("rating"),
        "google_review_count": candidate.get("user_ratings_total"),
        "google_maps_url": candidate.get("url"),
        "business_status": candidate.get("business_status"),
        "types": candidate.get("types", []),
        "coordinates": candidate.get("coordinates"),
        "distance_to_campus_miles": candidate.get("distance_to_campus_miles"),
        "classification": classification,
        "confidence_score": classification.get("confidence_score"),
        "housing_type": classification.get("housing_type"),
        "recommended_action": classification.get("recommended_action"),
        "discovered_at": now_iso(),
        "last_seen_at": now_iso(),
    }

    _db.property_candidates.update_one(
        {"google_place_id": place_id},
        {"$set": doc},
        upsert=True,
    )


def discover_properties():
    print("\n" + "=" * 64)
    print("  NESTIQ — Autonomous Auburn Property Discovery Agent")
    print("  Finding more off-campus housing candidates")
    print("=" * 64)

    if not PLACES_KEY:
        print("ERROR: GOOGLE_PLACES_API_KEY not found in .env")
        return

    campus = find_auburn_campus()
    campus_lat = campus["lat"]
    campus_lng = campus["lng"]

    print(f"\nCampus: {campus['name']}")
    print(f"Address: {campus.get('address')}")
    print(f"Coordinates: {campus_lat}, {campus_lng}")

    seen_place_ids = set()
    raw_results = []

    for query in SEARCH_QUERIES:
        print(f"\nSearching: {query}")

        try:
            data = google_text_search(query)

            for page_num in range(1, 4):
                status = data.get("status")
                if status not in {"OK", "ZERO_RESULTS"}:
                    print(f"  Google status: {status}")
                    break

                results = data.get("results", [])
                print(f"  Page {page_num}: {len(results)} results")

                for result in results:
                    place_id = result.get("place_id")
                    if not place_id or place_id in seen_place_ids:
                        continue

                    seen_place_ids.add(place_id)
                    raw_results.append(result)

                next_token = data.get("next_page_token")
                if not next_token:
                    break

                time.sleep(2.5)
                data = google_text_search(query, pagetoken=next_token)

        except Exception as e:
            print(f"  Search error: {e}")

        time.sleep(1)

    print(f"\nUnique Google Places results found: {len(raw_results)}")

    saved = 0
    ignored = 0
    too_far = 0
    duplicates = 0
    needs_review = 0

    for i, result in enumerate(raw_results):
        name = result.get("name", "Unknown")
        place_id = result.get("place_id")

        print(f"\n[{i + 1}/{len(raw_results)}] {name}")

        if already_known(place_id, name):
            print("  Already known. Skipping.")
            duplicates += 1
            continue

        details = get_place_details(place_id)
        if not details:
            print("  No details found. Skipping.")
            ignored += 1
            continue

        loc = details.get("geometry", {}).get("location", {})
        lat = loc.get("lat")
        lng = loc.get("lng")

        if lat is None or lng is None:
            print("  Missing coordinates. Skipping.")
            ignored += 1
            continue

        distance = haversine_miles(campus_lat, campus_lng, lat, lng)

        if distance > MAX_DISTANCE_MILES:
            print(f"  Too far from campus: {distance} miles. Skipping.")
            too_far += 1
            continue

        candidate = {
            "name": details.get("name") or name,
            "place_id": place_id,
            "formatted_address": details.get("formatted_address"),
            "website": details.get("website"),
            "formatted_phone_number": details.get("formatted_phone_number"),
            "rating": details.get("rating"),
            "user_ratings_total": details.get("user_ratings_total"),
            "business_status": details.get("business_status"),
            "types": details.get("types", []),
            "url": details.get("url"),
            "coordinates": {"lat": lat, "lng": lng},
            "distance_to_campus_miles": distance,
        }

        classification = classify_candidate_with_gemini(candidate)
        confidence = classification.get("confidence_score", 0)
        action = classification.get("recommended_action")
        is_housing = classification.get("is_student_housing")

        print(f"  Distance: {distance} miles")
        print(f"  Type: {classification.get('housing_type')}")
        print(f"  Student housing: {is_housing}")
        print(f"  Confidence: {confidence}")
        print(f"  Action: {action}")
        print(f"  Reason: {classification.get('reason')}")

        if action == "ignore" or (not is_housing and confidence >= 0.75):
            ignored += 1
            continue

        save_candidate(candidate, classification)

        if action == "needs_review":
            needs_review += 1
        else:
            saved += 1

        time.sleep(0.5)

    _db.property_discovery_runs.insert_one({
        "source": "google_places_discovery",
        "university_id": UNIVERSITY_ID,
        "university_name": UNIVERSITY_NAME,
        "started_and_finished_at": now_iso(),
        "queries": SEARCH_QUERIES,
        "unique_results_found": len(raw_results),
        "saved_candidates": saved,
        "needs_review": needs_review,
        "ignored": ignored,
        "duplicates": duplicates,
        "too_far": too_far,
        "max_distance_miles": MAX_DISTANCE_MILES,
    })

    total_candidates = _db.property_candidates.count_documents({
        "university_id": UNIVERSITY_ID
    })

    print("\n" + "=" * 64)
    print("  ✅ Discovery complete.")
    print(f"  Unique Google results: {len(raw_results)}")
    print(f"  Saved candidates: {saved}")
    print(f"  Needs review: {needs_review}")
    print(f"  Duplicates skipped: {duplicates}")
    print(f"  Too far skipped: {too_far}")
    print(f"  Ignored: {ignored}")
    print(f"  Total Auburn candidates in DB: {total_candidates}")
    print("=" * 64)


if __name__ == "__main__":
    discover_properties()
