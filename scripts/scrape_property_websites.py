"""
Nestiq Autonomous Property Website Scraper
Checks apartment websites for current pricing, availability, floor plans,
specials, amenities, lease terms, and policy details.

Run:
python -m scripts.scrape_property_websites
"""

import os
import re
import json
import time
import html
import urllib.request
import urllib.parse
from datetime import datetime
from urllib.parse import urlparse, urljoin
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

USER_AGENT = "Mozilla/5.0 (compatible; NestiqPropertyScraper/1.0; +https://nestiq.app)"
MAX_TEXT_CHARS = 28000


def now_iso() -> str:
    return datetime.utcnow().isoformat()


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def clean_text_from_html(raw_html: str) -> str:
    """Convert HTML into compact readable text for Gemini extraction."""
    raw_html = re.sub(r"<script[\s\S]*?</script>", " ", raw_html, flags=re.I)
    raw_html = re.sub(r"<style[\s\S]*?</style>", " ", raw_html, flags=re.I)
    raw_html = re.sub(r"<!--[\s\S]*?-->", " ", raw_html)
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_candidate_links(base_url: str, raw_html: str) -> list[str]:
    """Find useful same-domain links like floor plans, availability, amenities, specials."""
    links = re.findall(r'href=["\']([^"\']+)["\']', raw_html, flags=re.I)
    base_host = urlparse(base_url).netloc.replace("www.", "")
    useful_words = [
        "floor", "plan", "plans", "availability", "available", "rates",
        "pricing", "apartments", "amenities", "special", "specials",
        "lease", "leasing"
    ]

    candidates = []
    for link in links:
        if link.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue

        full = urljoin(base_url, link)
        parsed = urlparse(full)
        host = parsed.netloc.replace("www.", "")

        if host != base_host:
            continue

        lower = full.lower()
        if any(word in lower for word in useful_words):
            clean = full.split("#")[0].rstrip("/")
            if clean not in candidates:
                candidates.append(clean)

    return candidates[:4]


def fetch_url(url: str) -> tuple[str, str]:
    """Fetch a URL and return raw HTML + cleaned text."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as response:
        raw = response.read().decode("utf-8", errors="ignore")
    return raw, clean_text_from_html(raw)


def google_place_lookup(property_name: str, address: str | None = None) -> dict | None:
    """Use Google Places to find official website and Places metadata."""
    if not PLACES_KEY:
        return None

    query = f"{property_name} {address or ''} Auburn Alabama apartments"
    q = urllib.parse.quote(query)
    search_url = f"https://maps.googleapis.com/maps/api/place/textsearch/json?query={q}&key={PLACES_KEY}"

    try:
        with urllib.request.urlopen(search_url, timeout=20) as r:
            data = json.loads(r.read())

        if data.get("status") != "OK" or not data.get("results"):
            return None

        result = data["results"][0]
        place_id = result.get("place_id")

        details = {}
        if place_id:
            fields = urllib.parse.quote(
                "name,website,formatted_address,rating,user_ratings_total,place_id,url"
            )
            details_url = (
                "https://maps.googleapis.com/maps/api/place/details/json"
                f"?place_id={place_id}&fields={fields}&key={PLACES_KEY}"
            )
            with urllib.request.urlopen(details_url, timeout=20) as r:
                details_data = json.loads(r.read())
            if details_data.get("status") == "OK":
                details = details_data.get("result", {})

        return {
            "place_id": place_id,
            "google_name": details.get("name") or result.get("name"),
            "official_website": details.get("website"),
            "google_maps_url": details.get("url"),
            "google_rating": details.get("rating") or result.get("rating"),
            "google_review_count": details.get("user_ratings_total") or result.get("user_ratings_total"),
            "formatted_address": details.get("formatted_address") or result.get("formatted_address"),
        }

    except Exception as e:
        print(f"  Google Places lookup error: {e}")
        return None


def parse_json_response(raw: str) -> dict:
    """Parse Gemini JSON even if it wraps output in markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("```"))

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        raw = raw[start:end + 1]

    return json.loads(raw)


def extract_property_data_with_gemini(property_doc: dict, website_url: str, page_text: str, source_urls: list[str]) -> dict:
    """Use Gemini to extract structured apartment data from website text."""
    current_snapshot = {
        "property_id": property_doc.get("property_id"),
        "name": property_doc.get("name"),
        "current_rent_min": property_doc.get("rent_min"),
        "current_rent_max": property_doc.get("rent_max"),
        "current_rent_per_person": property_doc.get("rent_per_person"),
        "current_bedrooms_available": property_doc.get("bedrooms_available"),
        "current_amenities": property_doc.get("amenities"),
        "current_available_date": property_doc.get("available_date"),
        "current_description": property_doc.get("description"),
    }

    prompt = f"""
You are extracting current apartment website data for Nestiq, a student housing intelligence app.

Property:
{json.dumps(current_snapshot, indent=2)}

Official website:
{website_url}

Source URLs:
{json.dumps(source_urls, indent=2)}

Website text:
\"\"\"
{page_text[:MAX_TEXT_CHARS]}
\"\"\"

Extract ONLY facts that are clearly supported by the website text.
Do not guess.
If a value is not clearly stated, use null or an empty list.
For rent, prefer per-person student housing pricing when stated.
Return ONLY valid JSON in this exact shape:

{{
  "property_name": "string",
  "official_website": "string",
  "current_rent_min": number or null,
  "current_rent_max": number or null,
  "rent_notes": "string or null",
  "floor_plans": [
    {{
      "name": "string or null",
      "beds": number or null,
      "baths": number or null,
      "rent": number or null,
      "rent_text": "string or null",
      "availability": "string or null"
    }}
  ],
  "bedroom_options": [number],
  "availability_status": "available, limited availability, waitlist, sold out, unknown, or null",
  "available_date": "YYYY-MM-DD or null",
  "move_in_specials": ["list of current specials"],
  "lease_terms": ["list of lease term facts"],
  "amenities": ["list of amenities clearly stated"],
  "utilities_included": ["list of utilities clearly stated as included"],
  "pet_policy": "string or null",
  "parking_info": "string or null",
  "confidence_score": number between 0 and 1,
  "source_urls": ["urls used"],
  "extracted_at": "{now_iso()}"
}}
"""

    try:
        response = _genai.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Part.from_text(text=prompt)],
        )
        return parse_json_response(response.text)
    except Exception as e:
        print(f"  Gemini extraction error: {e}")
        return {
            "property_name": property_doc.get("name"),
            "official_website": website_url,
            "current_rent_min": None,
            "current_rent_max": None,
            "rent_notes": None,
            "floor_plans": [],
            "bedroom_options": [],
            "availability_status": None,
            "available_date": None,
            "move_in_specials": [],
            "lease_terms": [],
            "amenities": [],
            "utilities_included": [],
            "pet_policy": None,
            "parking_info": None,
            "confidence_score": 0,
            "source_urls": source_urls,
            "extracted_at": now_iso(),
        }


def safe_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace(",", "")
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def meaningful(value) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if value == []:
        return False
    if isinstance(value, str) and value.strip().lower() in {"unknown", "n/a", "null", "none"}:
        return False
    return True


def values_different(old, new) -> bool:
    if old is None and new is None:
        return False
    return old != new


def log_property_update(pid: str, name: str, field: str, old_value, new_value, confidence: float, source_urls: list[str]):
    _db.property_updates.insert_one({
        "property_id": pid,
        "property_name": name,
        "source": "autonomous_property_scraper",
        "field_changed": field,
        "old_value": old_value,
        "new_value": new_value,
        "confidence_score": confidence,
        "source_urls": source_urls,
        "detected_at": now_iso(),
    })


def compare_and_update_property(property_doc: dict, extracted: dict) -> int:
    """Compare extracted website data to MongoDB property doc and update conservatively."""
    pid = property_doc["property_id"]
    name = property_doc["name"]
    confidence = float(extracted.get("confidence_score") or 0)
    source_urls = extracted.get("source_urls", [])

    updates = {}
    changes = 0

    # Conservative field mapping.
    candidates = {
        "website": extracted.get("official_website"),
        "rent_min": safe_number(extracted.get("current_rent_min")),
        "rent_max": safe_number(extracted.get("current_rent_max")),
        "bedrooms_available": extracted.get("bedroom_options"),
        "availability_status": extracted.get("availability_status"),
        "available_date": extracted.get("available_date"),
        "move_in_specials": extracted.get("move_in_specials"),
        "lease_terms": extracted.get("lease_terms"),
        "amenities": extracted.get("amenities"),
        "utilities_included_list": extracted.get("utilities_included"),
        "pet_policy_text": extracted.get("pet_policy"),
        "parking_info": extracted.get("parking_info"),
        "floor_plans": extracted.get("floor_plans"),
        "rent_notes": extracted.get("rent_notes"),
    }

    for field, new_value in candidates.items():
        if not meaningful(new_value):
            continue

        old_value = property_doc.get(field)

        # Rent should be high-confidence only.
        if field in {"rent_min", "rent_max"} and confidence < 0.75:
            continue

        # Availability should be reasonably confident.
        if field in {"availability_status", "available_date"} and confidence < 0.70:
            continue

        # Avoid overwriting strong existing amenities with tiny scraped lists.
        if field == "amenities":
            old_list = property_doc.get("amenities") or []
            new_list = new_value or []
            if len(new_list) < 3 or len(new_list) < len(old_list) * 0.5:
                continue

        if values_different(old_value, new_value):
            log_property_update(pid, name, field, old_value, new_value, confidence, source_urls)
            updates[field] = new_value
            changes += 1

    if updates:
        updates["last_scraped_at"] = now_iso()
        updates["scraper_confidence_score"] = confidence
        updates["scraper_source_urls"] = source_urls
        _db.properties.update_one({"property_id": pid}, {"$set": updates})

    return changes


def collect_website_text(website_url: str) -> tuple[str, list[str]]:
    """Fetch homepage plus a few relevant same-domain pages."""
    website_url = normalize_url(website_url)
    if not website_url:
        return "", []

    source_urls = []
    combined_text = ""

    try:
        raw_html, text = fetch_url(website_url)
        source_urls.append(website_url)
        combined_text += f"\n\nSOURCE: {website_url}\n{text}"

        links = extract_candidate_links(website_url, raw_html)

        for link in links[:3]:
            try:
                raw2, text2 = fetch_url(link)
                source_urls.append(link)
                combined_text += f"\n\nSOURCE: {link}\n{text2}"
                time.sleep(0.5)
            except Exception:
                continue

    except Exception as e:
        print(f"  Website fetch error: {e}")

    return combined_text[:MAX_TEXT_CHARS], source_urls


def scrape_property(property_doc: dict) -> int:
    """Scrape one property and return number of changes saved."""
    pid = property_doc["property_id"]
    name = property_doc["name"]
    address = property_doc.get("address")

    print(f"\n  Checking {name}...")

    website = (
        property_doc.get("website")
        or property_doc.get("official_website")
        or property_doc.get("url")
    )

    place = None
    if not website:
        print("  No website in MongoDB. Looking up official website with Google Places...")
        place = google_place_lookup(name, address)
        if place:
            website = place.get("official_website")
            if place.get("place_id") or place.get("google_rating"):
                _db.properties.update_one(
                    {"property_id": pid},
                    {"$set": {
                        "google_place_id": place.get("place_id"),
                        "google_rating": place.get("google_rating"),
                        "google_review_count": place.get("google_review_count"),
                        "website": website,
                        "google_maps_url": place.get("google_maps_url"),
                        "last_places_lookup_at": now_iso(),
                    }}
                )

    website = normalize_url(website)

    if not website:
        print("  ✗ Could not find official website.")
        return 0

    print(f"  Website: {website}")

    page_text, source_urls = collect_website_text(website)

    if len(page_text) < 500:
        print("  ✗ Not enough website text extracted.")
        return 0

    print(f"  Extracted {len(page_text):,} characters from {len(source_urls)} page(s).")
    extracted = extract_property_data_with_gemini(property_doc, website, page_text, source_urls)

    confidence = float(extracted.get("confidence_score") or 0)
    rent_min = extracted.get("current_rent_min")
    rent_max = extracted.get("current_rent_max")
    status = extracted.get("availability_status")

    if rent_min or rent_max:
        print(f"  Found rent range: ${rent_min or '?'}-${rent_max or '?'}")
    if status:
        print(f"  Found availability status: {status}")
    if extracted.get("move_in_specials"):
        print(f"  Found specials: {', '.join(extracted['move_in_specials'][:2])}")
    print(f"  Confidence: {confidence}")

    changes = compare_and_update_property(property_doc, extracted)
    print(f"  Changes detected: {changes}")

    time.sleep(1)
    return changes


def scrape_all_properties():
    print("\n" + "=" * 60)
    print("  NESTIQ — Autonomous Property Website Scraper")
    print("  Checking apartment websites for current data")
    print("=" * 60)

    started_at = now_iso()

    properties = list(_db.properties.find({}))
    print(f"\nFound {len(properties)} properties to process.")

    total_updated = 0
    total_changes = 0
    errors = []

    for i, prop in enumerate(properties):
        print(f"\n[{i + 1}/{len(properties)}] {prop.get('name')}")
        try:
            changes = scrape_property(prop)
            total_changes += changes
            if changes > 0:
                total_updated += 1
        except Exception as e:
            msg = f"{prop.get('name')}: {e}"
            errors.append(msg)
            print(f"  ✗ Error: {e}")

    finished_at = now_iso()

    _db.property_scraper_runs.insert_one({
        "source": "autonomous_property_scraper",
        "started_at": started_at,
        "finished_at": finished_at,
        "total_properties_checked": len(properties),
        "total_properties_updated": total_updated,
        "total_changes_detected": total_changes,
        "errors": errors,
    })

    print("\n" + "=" * 60)
    print(f"  ✅ Scraper complete.")
    print(f"  Properties checked: {len(properties)}")
    print(f"  Properties updated: {total_updated}")
    print(f"  Total changes detected: {total_changes}")
    print(f"  Errors: {len(errors)}")
    print("=" * 60)


if __name__ == "__main__":
    scrape_all_properties()
