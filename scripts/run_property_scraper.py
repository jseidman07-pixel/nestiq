#!/usr/bin/env python3
"""
Run the Autonomous Property Scraper Agent.
Scrapes all 21 Auburn properties for current pricing, availability, and specials.
Can be run manually or scheduled as a cron job.
"""

import json
import sys
sys.path.insert(0, '/Users/jennaseidman/nestiq')

from agents.scraper.agent import scrape_all_properties

if __name__ == "__main__":
    print("🏢 Starting Autonomous Property Scraper...")
    print("Visiting all 21 Auburn property websites...\n")

    summary = scrape_all_properties()

    print(f"\n✅ Scrape complete!")
    print(f"   Updated: {summary['updated']}")
    print(f"   No changes: {summary['no_changes']}")
    print(f"   Errors: {summary['errors']}")
    print(f"   Skipped: {summary['skipped']}")
    print(f"\nFull results:")
    print(json.dumps(summary, indent=2))
