"""
Nestiq Candidate Tagger
Adds housing_category and review_priority to Auburn property candidates.

Run:
python -m scripts.tag_auburn_candidates
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(".env")

db = MongoClient(os.getenv("MONGODB_URI"))[os.getenv("MONGODB_DATABASE", "nestiq")]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def choose_housing_category(candidate):
    housing_type = (candidate.get("housing_type") or "").lower()
    name = (candidate.get("property_name") or "").lower()

    if "townhome" in housing_type or "townhome" in name:
        return "off_campus_townhome"

    if "cottage" in housing_type or "cottage" in name:
        return "off_campus_cottage"

    if "student" in housing_type:
        return "off_campus_student_apartment"

    if "apartment" in housing_type or "apartments" in name:
        return "off_campus_general_apartment"

    return "candidate_needs_review"


def choose_review_priority(candidate):
    distance = candidate.get("distance_to_campus_miles")
    review_count = candidate.get("google_review_count") or 0
    rating = candidate.get("google_rating")
    website = candidate.get("website")
    confidence = candidate.get("confidence_score") or 0
    housing_type = (candidate.get("housing_type") or "").lower()

    # Strong candidates: close, enough reviews, has a website, high confidence.
    if (
        website
        and distance is not None
        and distance <= 2.25
        and review_count >= 75
        and confidence >= 0.90
    ):
        return "approve_first"

    # Also approve if clearly student housing and very close, even with fewer reviews.
    if (
        website
        and distance is not None
        and distance <= 1.25
        and confidence >= 0.95
        and "student" in housing_type
    ):
        return "approve_first"

    # Needs human review if missing key trust signals.
    if not website or review_count < 10:
        return "needs_review"

    # Farther places should wait unless you deliberately want wider Auburn coverage.
    if distance is not None and distance > 3.0:
        return "hold_for_later"

    return "review_next"


def main():
    candidates = list(db.property_candidates.find({"university_id": "auburn_university"}))

    print("\n" + "=" * 64)
    print("  NESTIQ — Auburn Candidate Tagger")
    print("  Categorizing discovered housing candidates")
    print("=" * 64)
    print(f"\nFound {len(candidates)} candidates.\n")

    counts = {}

    for c in candidates:
        category = choose_housing_category(c)
        priority = choose_review_priority(c)

        db.property_candidates.update_one(
            {"_id": c["_id"]},
            {
                "$set": {
                    "housing_category": category,
                    "review_priority": priority,
                    "tagged_at": now_iso(),
                }
            },
        )

        counts[priority] = counts.get(priority, 0) + 1

        print(f"{c.get('property_name')}")
        print(f"  Category: {category}")
        print(f"  Priority: {priority}")
        print(f"  Distance: {c.get('distance_to_campus_miles')} mi")
        print(f"  Rating: {c.get('google_rating')} ({c.get('google_review_count')} reviews)")
        print()

    print("=" * 64)
    print("  ✅ Tagging complete.")
    for key, value in sorted(counts.items()):
        print(f"  {key}: {value}")
    print("=" * 64)


if __name__ == "__main__":
    main()
