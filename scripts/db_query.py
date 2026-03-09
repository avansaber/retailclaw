#!/usr/bin/env python3
"""RetailClaw -- db_query.py (unified router)

AI-native retail management: pricing, promotions, loyalty programs, merchandising,
wholesale/B2B, returns & exchanges.
Routes all actions across 6 domain modules.

Usage: python3 db_query.py --action <action-name> [--flags ...]
Output: JSON to stdout, exit 0 on success, exit 1 on error.
"""
import argparse
import json
import os
import sys

# Add shared lib to path
try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection, ensure_db_exists, DEFAULT_DB_PATH
    from erpclaw_lib.validation import check_input_lengths
    from erpclaw_lib.response import ok, err
    from erpclaw_lib.dependencies import check_required_tables
except ImportError:
    import json as _json
    print(_json.dumps({
        "status": "error",
        "error": "ERPClaw foundation not installed. Install erpclaw-setup first: clawhub install erpclaw-setup",
        "suggestion": "clawhub install erpclaw-setup"
    }))
    sys.exit(1)

# Add this script's directory so domain modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pricing import ACTIONS as PRICING_ACTIONS
from loyalty import ACTIONS as LOYALTY_ACTIONS
from merchandising import ACTIONS as MERCHANDISING_ACTIONS
from wholesale import ACTIONS as WHOLESALE_ACTIONS
from returns import ACTIONS as RETURNS_ACTIONS
from reports import ACTIONS as REPORTS_ACTIONS

# ---------------------------------------------------------------------------
# Merge all domain actions into one router
# ---------------------------------------------------------------------------
SKILL = "retailclaw"
REQUIRED_TABLES = ["company", "retailclaw_price_list"]

ACTIONS = {}
ACTIONS.update(PRICING_ACTIONS)
ACTIONS.update(LOYALTY_ACTIONS)
ACTIONS.update(MERCHANDISING_ACTIONS)
ACTIONS.update(WHOLESALE_ACTIONS)
ACTIONS.update(RETURNS_ACTIONS)
ACTIONS.update(REPORTS_ACTIONS)


def main():
    parser = argparse.ArgumentParser(description="retailclaw")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS.keys()))
    parser.add_argument("--db-path", default=None)

    # -- Shared IDs --
    parser.add_argument("--company-id")
    parser.add_argument("--customer-id")
    parser.add_argument("--item-id")

    # -- Shared --
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--notes")
    parser.add_argument("--status")
    parser.add_argument("--description")
    parser.add_argument("--name")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--currency")

    # ── PRICING domain ────────────────────────────────────────────
    parser.add_argument("--price-list-id")
    parser.add_argument("--price-list-type")
    parser.add_argument("--price-list-status")
    parser.add_argument("--is-default")
    parser.add_argument("--valid-from")
    parser.add_argument("--valid-to")
    parser.add_argument("--price-list-item-id")
    parser.add_argument("--rate")
    parser.add_argument("--min-qty")
    parser.add_argument("--item-name")
    # -- Promotions --
    parser.add_argument("--promotion-id")
    parser.add_argument("--promo-type")
    parser.add_argument("--promo-status")
    parser.add_argument("--discount-value")
    parser.add_argument("--min-purchase")
    parser.add_argument("--max-discount")
    parser.add_argument("--max-uses")
    parser.add_argument("--applicable-items")
    parser.add_argument("--applicable-categories")

    # ── LOYALTY domain ────────────────────────────────────────────
    parser.add_argument("--program-id")
    parser.add_argument("--program-status")
    parser.add_argument("--points-per-dollar")
    parser.add_argument("--redemption-rate")
    parser.add_argument("--tiers")
    parser.add_argument("--member-id")
    parser.add_argument("--member-tier")
    parser.add_argument("--member-status")
    parser.add_argument("--customer-name")
    parser.add_argument("--email")
    parser.add_argument("--phone")
    parser.add_argument("--enrollment-date")
    parser.add_argument("--points", type=int)
    parser.add_argument("--reference-type")
    parser.add_argument("--reference-id")
    # -- Gift card --
    parser.add_argument("--gift-card-id")
    parser.add_argument("--card-number")
    parser.add_argument("--initial-balance")
    parser.add_argument("--issue-date")
    parser.add_argument("--expiration-date")
    parser.add_argument("--purchaser-name")
    parser.add_argument("--recipient-name")
    parser.add_argument("--recipient-email")
    parser.add_argument("--amount")

    # ── MERCHANDISING domain ──────────────────────────────────────
    parser.add_argument("--category-id")
    parser.add_argument("--parent-id")
    parser.add_argument("--sort-order")
    parser.add_argument("--is-active")
    parser.add_argument("--planogram-id")
    parser.add_argument("--planogram-status")
    parser.add_argument("--store-section")
    parser.add_argument("--fixture-type")
    parser.add_argument("--shelf-count")
    parser.add_argument("--width-inches")
    parser.add_argument("--height-inches")
    parser.add_argument("--effective-date")
    parser.add_argument("--shelf-number")
    parser.add_argument("--position")
    parser.add_argument("--facings")
    parser.add_argument("--min-stock")
    parser.add_argument("--max-stock")

    # ── WHOLESALE domain ──────────────────────────────────────────
    parser.add_argument("--wholesale-customer-id")
    parser.add_argument("--wholesale-status")
    parser.add_argument("--business-name")
    parser.add_argument("--contact-name")
    parser.add_argument("--tax-id")
    parser.add_argument("--credit-limit")
    parser.add_argument("--payment-terms")
    parser.add_argument("--discount-pct")
    parser.add_argument("--address-line1")
    parser.add_argument("--address-line2")
    parser.add_argument("--city")
    parser.add_argument("--state")
    parser.add_argument("--zip-code")
    parser.add_argument("--wholesale-rate")
    parser.add_argument("--min-order-qty")
    parser.add_argument("--wholesale-order-id")
    parser.add_argument("--order-date")
    parser.add_argument("--order-status")
    parser.add_argument("--expected-delivery-date")
    parser.add_argument("--qty")

    # ── RETURNS domain ────────────────────────────────────────────
    parser.add_argument("--return-id")
    parser.add_argument("--return-date")
    parser.add_argument("--return-type")
    parser.add_argument("--return-status")
    parser.add_argument("--reason")
    parser.add_argument("--original-invoice-id")
    parser.add_argument("--restocking-fee")
    parser.add_argument("--item-condition")
    parser.add_argument("--disposition")
    parser.add_argument("--original-item-id")
    parser.add_argument("--original-item-name")
    parser.add_argument("--new-item-id")
    parser.add_argument("--new-item-name")
    parser.add_argument("--price-difference")

    # ── GL Posting (optional, for process-return) ──────────────────
    parser.add_argument("--sales-returns-account-id", help="GL account for Sales Returns & Allowances (debit)")
    parser.add_argument("--cash-account-id", help="GL account for Cash/AR (credit for refund)")
    parser.add_argument("--inventory-account-id", help="GL account for Inventory (debit on restock)")
    parser.add_argument("--cogs-account-id", help="GL account for COGS (credit on restock)")
    parser.add_argument("--cost-center-id", help="Cost center for P&L GL entries")
    parser.add_argument("--restock-cost", help="Total cost of restocked inventory items")

    args = parser.parse_args()
    action = args.action

    # DB setup
    db_path = args.db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    ensure_db_exists(db_path)

    conn = get_connection(db_path) if args.db_path else get_connection()

    # Check required tables exist
    check_required_tables(conn, REQUIRED_TABLES)

    # Dispatch
    handler = ACTIONS[action]
    handler(conn, args)


if __name__ == "__main__":
    main()
