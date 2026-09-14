#!/usr/bin/env python
"""
Quick-start guide demonstrating the complete ORCA data ingestion pipeline.

This script shows how to populate the ORCA database with realistic demo data
using all available ingestion modules, with intelligent fallback to mock data
if live sources are unavailable.

Usage:
    python ingestion/quickstart_demo.py --help
    python ingestion/quickstart_demo.py \\
        --database-url "postgresql://orca_user:pass@localhost/orca" \\
        --region south_tamil_nadu \\
        --use-mock-data
"""

import argparse
import sys
import os
from datetime import datetime

# Ensure both src and root are in path for imports
# When running from repo root, both ingestion and src packages should be accessible
if os.path.dirname(__file__):
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

from ingestion.populate_demo_dataset import (
    DEMO_REGIONS,
    main as populate_main,
)
from orca.config import settings


def verify_database_connection(database_url: str) -> bool:
    """Quick test to verify database is reachable."""
    try:
        from orca.knowledge.database import PostGISDatabase
        db = PostGISDatabase(database_url)
        # Try a simple query
        db.execute("SELECT 1")
        return True
    except Exception as e:
        print(f"Database connection failed: {e}")
        return False


def show_demo_info():
    """Display information about available demo configurations."""
    print("\n" + "="*70)
    print("ORCA Data Ingestion Demo")
    print("="*70)
    print("\nAvailable demo regions:")
    for key, region in DEMO_REGIONS.items():
        bounds = f"[{region['min_lat']}, {region['max_lat']}] x [{region['min_lon']}, {region['max_lon']}]"
        print(f"  • {key:20} — {region['name']}")
        print(f"    Bounds: {bounds}\n")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--database-url",
        default=settings.database_url,
        help="PostgreSQL connection string (default: ORCA_DATABASE_URL env)",
    )
    parser.add_argument(
        "--region",
        choices=list(DEMO_REGIONS.keys()),
        default="south_tamil_nadu",
        help="Demo region to populate",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Date for data ingestion (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--use-mock-data",
        action="store_true",
        help="Use mock data only (no network calls)",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Show demo info and exit",
    )

    args = parser.parse_args()

    if args.info:
        show_demo_info()
        return

    if not args.database_url:
        print("ERROR: No database URL provided.")
        print("  Set ORCA_DATABASE_URL environment variable or use --database-url")
        sys.exit(1)

    print("Verifying database connection...")
    if not verify_database_connection(args.database_url):
        print("ERROR: Cannot connect to database")
        sys.exit(1)

    print("✓ Database connection verified")

    # Call the orchestration function
    sys.argv = [
        "populate_demo_dataset.py",
        "--database-url", args.database_url,
        "--region", args.region,
        "--date", args.date,
    ]
    if args.use_mock_data:
        sys.argv.append("--skip-live-sources")

    populate_main()


if __name__ == "__main__":
    main()
