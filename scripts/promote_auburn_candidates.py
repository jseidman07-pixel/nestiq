"""
Nestiq Candidate Promotion Script
Promotes high-quality Auburn property candidates into the live properties collection.

Dry run:
python -m scripts.promote_auburn_candidates

Apply:
python -m scripts.promote_auburn_candidates --apply
"""

import os
import re
import argparse
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")

db = MongoClient(os.getenv("MONGODB_URI"))[os.getenv("MONGODB_DATABASE", "nestiq")]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:70]


def estimate_walk_time(distance_miles):
    if distance_miles is None:
        return None
    # About 3 mph walking speed.
    return max(1, round((distance_miles / 3) * 60))


def estimate_drive_time(distance_miles):
    if distance_miles is None:
        return None
    # Rough Auburn local driving estimate, with minimum realistic campus drive.
    return max(3, round((distance_miles / 18) * 60))


def make_tags(candidate):
    tags = []

    category = candidate.get("housing_category")
    name = (candidate.get("property_name") or "").lower()
    rating = candidate.get("google_rating")
    distance = candidate.get("distance_to_campus_miles")

    if category == "off_campus_student_apartment":
        tags.append("student-housing")
    if category == "off_campus_townhome":
        tags.append("townhome")
    if category == "off_campus_cottage":
        tags.append("cottage")
    if distance is not None and distance <= 1.0:
        tags.append("close-to-campus")
    if distance is not None and distance <= 1.5:
        tags.append("walkable")
    if rating is not None and rating >= 4.5:
        tags.append("high-rated")
    if "village" in name:
        tags.append("community-style")
    if "quarters" in name or "college" in name or "bragg" in name:
        tags.append("student-focused")

    return list(dict.fromkeys(tags))


def build_description(candidate):
    name = candidate.get("property_name")
    distance = candidate.get("distance_to_campus_miles")
    rating = candidate.get("google_rating")
    reviews = candidate.get("google_review_count")
    category = candidate.get("housing_category", "off-campus housing")
    reason = (candidate.get("classification") or {}).get("reason")

    parts = [
        f"{name} is a newly discovered {category.replace('_', ' ')} option near Auburn University."
    ]

    if distance is not None:
        parts.append(f"It is approximately {distance} miles from campus.")

    if rating is not None and reviews is not None:
        parts.append(f"Google Places shows a {rating} star rating from {reviews} reviews.")

    if reason:
        parts.append(f"Discovery note: {reason}")

    parts.append(
        "Pricing, floor plans, amenities, and availability still need enrichment from the official property website."
    )

    return " ".join(parts)


def build_embedding_text(doc):
    return f"""
{doc.get('name')} is an Auburn housing property.
Category: {doc.get('housing_category')}.
Address: {doc.get('address')}.
Distance to Auburn University: {doc.get('distance_to_campus_miles')} miles.
Google rating: {doc.get('google_rating')} from {doc.get('google_review_count')} reviews.
Description: {doc.get('description')}.
Tags: {', '.join(doc.get('tags', []))}.
Data status: newly discovered candidate, needs website scraping and enrichment.
""".strip()


def candidate_already_promoted(candidate):
    place_id = candidate.get("google_place_id")
    name = candidate.get("property_name")
    slug = slugify(name)

    query = {
        "$or": [
            {"google_place_id": place_id},
            {"property_id": f"nestiq_auto_{slug}"},
            {"name": name},
        ]
    }

    # Remove place_id check if missing so Mongo doesn't match null weirdly.
    if not place_id:
        query = {
            "$or": [
                {"property_id": f"nestiq_auto_{slug}"},
                {"name": name},
            ]
        }

    return db.properties.find_one(query)


def make_property_doc(candidate):
    name = candidate.get("property_name")
    slug = slugify(name)

    coords = candidate.get("coordinates") or {}
    lat = coords.get("lat")
    lng = coords.get("lng")

    geo = None
    if lat is not None and lng is not None:
        geo = {
            "type": "Point",
            "coordinates": [lng, lat],
        }

    doc = {
        "property_id": f"nestiq_auto_{slug}",
        "name": name,
        "address": candidate.get("address"),
        "website": candidate.get("website"),
        "phone": candidate.get("phone"),

        # School fields
        "university": "auburn",
        "university_id": "auburn_university",
        "university_name": "Auburn University",

        # Location
        "coordinates": geo,
        "distance_to_campus_miles": candidate.get("distance_to_campus_miles"),
        "walk_time_minutes": estimate_walk_time(candidate.get("distance_to_campus_miles")),
        "drive_time_minutes": estimate_drive_time(candidate.get("distance_to_campus_miles")),
        "tiger_transit": None,

        # Pricing starts unknown until scraper enriches it.
        "rent_min": None,
        "rent_max": None,
        "price_tier": "unknown",
        "utilities_estimate_monthly": None,
        "fees": {},

        # Housing info starts basic.
        "housing_category": candidate.get("housing_category"),
        "bedrooms_available": [],
        "floor_plans": [],
        "amenities": [],
        "tags": make_tags(candidate),
        "description": build_description(candidate),

        # Google Places / reputation
        "google_place_id": candidate.get("google_place_id"),
        "google_maps_url": candidate.get("google_maps_url"),
        "google_rating": candidate.get("google_rating"),
        "google_review_count": candidate.get("google_review_count"),
        "reputation_score": candidate.get("google_rating"),

        # Discovery metadata
        "source": "google_places_discovery",
        "status": "live_needs_enrichment",
        "enrichment_status": "needs_website_scrape",
        "discovery_confidence_score": candidate.get("confidence_score"),
        "discovered_at": candidate.get("discovered_at"),
        "promoted_at": now_iso(),
        "promoted_from_candidate_id": candidate.get("candidate_id"),
        "review_priority": candidate.get("review_priority"),

        # Important for vector search later, but embedding itself is not generated here.
        "embedding_text": None,
        "embedding_needed": True,
    }

    doc["embedding_text"] = build_embedding_text(doc)

    return doc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually insert promoted properties")
    args = parser.parse_args()

    candidates = list(db.property_candidates.find({
        "university_id": "auburn_university",
        "review_priority": "approve_first",
    }).sort("distance_to_campus_miles", 1))

    print("\n" + "=" * 70)
    print("  NESTIQ — Promote Auburn Candidates")
    print("=" * 70)
    print(f"\nMode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Approve-first candidates found: {len(candidates)}\n")

    promoted = 0
    skipped = 0

    for c in candidates:
        name = c.get("property_name")
        existing = candidate_already_promoted(c)

        if existing:
            print(f"SKIP existing: {name} -> {existing.get('property_id')}")
            skipped += 1
            continue

        doc = make_property_doc(c)

        print(f"PROMOTE: {name}")
        print(f"  New property_id: {doc['property_id']}")
        print(f"  Category: {doc.get('housing_category')}")
        print(f"  Distance: {doc.get('distance_to_campus_miles')} mi")
        print(f"  Rating: {doc.get('google_rating')} ({doc.get('google_review_count')} reviews)")
        print(f"  Website: {doc.get('website')}")
        print(f"  Status: {doc.get('status')}")
        print()

        if args.apply:
            db.properties.insert_one(doc)
            db.property_candidates.update_one(
                {"_id": c["_id"]},
                {"$set": {
                    "status": "promoted",
                    "promoted_property_id": doc["property_id"],
                    "promoted_at": now_iso(),
                }},
            )

        promoted += 1

    if args.apply:
        db.property_promotion_runs.insert_one({
            "source": "candidate_promotion",
            "university_id": "auburn_university",
            "review_priority": "approve_first",
            "promoted_count": promoted,
            "skipped_count": skipped,
            "created_at": now_iso(),
        })

    total_properties = db.properties.count_documents({})
    total_candidates = db.property_candidates.count_documents({"university_id": "auburn_university"})

    print("=" * 70)
    print("  Summary")
    print(f"  Would promote / promoted: {promoted}")
    print(f"  Skipped existing: {skipped}")
    print(f"  Total live properties now: {total_properties}")
    print(f"  Total Auburn candidates: {total_candidates}")
    print("=" * 70)

    if not args.apply:
        print("\nDry run only. To actually promote them, run:")
        print("python -m scripts.promote_auburn_candidates --apply")


if __name__ == "__main__":
    main()
