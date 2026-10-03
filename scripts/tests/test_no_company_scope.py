"""Company scope for retail lists and reports (m792-nocompany-p9-retailclaw).

A list or report that takes an optional company answers for exactly one
company through resolve_scope_company: no company with zero companies
refuses, no company with one company uses it, no company with several
companies refuses, an unknown --company-id refuses, and --company resolves
an exact case-insensitive name (a miss refuses). The refusal happens before
the action reads its own tables, so every refusal also pins the database
unchanged. Successful results gain no new top-level key.
"""
import json

import pytest

from retail_helpers import (
    call_action, ns, is_ok, load_db_query, seed_company,
)
from erpclaw_lib.query import Q, P, Table

mod = load_db_query()

ACME_NAME = "Acme Widgets"
ACME_ABBR = "ACME"
WAYNE_NAME = "Wayne Enterprises"
WAYNE_ABBR = "WAYNE"

ZERO_COMPANY_ERROR = "No company found. Create one first."
ZERO_COMPANY_SUGGESTION = "Run 'tutorial' to create a demo company, or 'setup company' to create your own."
MULTI_COMPANY_ERROR = "Multiple companies found. Please specify the company by name."
MULTI_COMPANY_SUGGESTION = "Pass the company name (e.g. --company \"Acme\"), or use --company-id with one of the IDs above."
NAME_MISS_SUGGESTION = "Use one of the available company names exactly, or run 'list-companies' to see them."

_STATE_TABLES = (
    "retailclaw_price_list",
    "retailclaw_price_list_item",
    "retailclaw_promotion",
    "retailclaw_coupon",
    "retailclaw_loyalty_program",
    "retailclaw_loyalty_member",
    "retailclaw_loyalty_transaction",
    "retailclaw_gift_card",
    "retailclaw_category",
    "retailclaw_planogram",
    "retailclaw_planogram_item",
    "retailclaw_wholesale_customer",
    "retailclaw_wholesale_price",
    "retailclaw_wholesale_order",
    "retailclaw_wholesale_order_item",
    "retailclaw_return_authorization",
    "retailclaw_return_item",
    "retailclaw_exchange",
    "retailclaw_store_location",
    "retailclaw_shrinkage",
    "retailclaw_store_credit",
    "company",
    "audit_log",
)

ALL_ACTIONS = [
    "retail-list-shrinkage",
    "retail-channel-performance",
    "retail-margin-analysis",
    "retail-loyalty-report",
    "retail-category-performance",
    "retail-promotion-effectiveness",
    "retail-inventory-turnover",
]

_ACTION_FNS = {
    "retail-list-shrinkage": mod.retail_list_shrinkage,
    "retail-channel-performance": mod.retail_channel_performance,
    "retail-margin-analysis": mod.retail_margin_analysis,
    "retail-loyalty-report": mod.retail_loyalty_report,
    "retail-category-performance": mod.retail_category_performance,
    "retail-promotion-effectiveness": mod.retail_promotion_effectiveness,
    "retail-inventory-turnover": mod.retail_inventory_turnover,
}


def _seed_exact_companies(conn):
    """Two companies with EXACT names via seed_company.

    seed_company() appends a uuid suffix to name and abbr
    ("Acme Widgets a1b2c3"), which would break exact-name resolution, so
    normalize both rows back to their exact values here.
    """
    acme = seed_company(conn, ACME_NAME, ACME_ABBR)
    wayne = seed_company(conn, WAYNE_NAME, WAYNE_ABBR)
    t = Table("company")
    for cid, name, abbr in ((acme, ACME_NAME, ACME_ABBR),
                            (wayne, WAYNE_NAME, WAYNE_ABBR)):
        uq = (Q.update(t).set("name", P()).set("abbr", P())
              .where(t.id == P()))
        conn.execute(uq.get_sql(), (name, abbr, cid))
    conn.commit()
    return acme, wayne


def _seed_acme_only(conn):
    """One company with its exact name via seed_company (see above)."""
    acme = seed_company(conn, ACME_NAME, ACME_ABBR)
    t = Table("company")
    uq = (Q.update(t).set("name", P()).set("abbr", P())
          .where(t.id == P()))
    conn.execute(uq.get_sql(), (ACME_NAME, ACME_ABBR, acme))
    conn.commit()
    return acme


def _seed_company_books(conn, company_id, price_list_name, category_name,
                        quantity):
    """One price list, one category and one shrinkage record, through the
    module's own add actions."""
    created_pl = call_action(mod.retail_add_price_list, conn, ns(
        company_id=company_id, name=price_list_name, description=None,
        price_list_type="selling", currency="USD", is_default=None,
        valid_from=None, valid_to=None))
    assert is_ok(created_pl), created_pl
    created_cat = call_action(mod.retail_add_category, conn, ns(
        company_id=company_id, name=category_name, parent_id=None,
        description=None, sort_order=1))
    assert is_ok(created_cat), created_cat
    created_sh = call_action(mod.retail_record_shrinkage, conn, ns(
        company_id=company_id, store_location_id=None, item_id=None,
        quantity=quantity, cause="theft", discovered_date="2026-09-01",
        reported_by=None, value_lost=None, notes=None))
    assert is_ok(created_sh), created_sh


def _seed_both_books(conn, acme, wayne):
    _seed_company_books(conn, acme, "Acme Retail", "Acme Tools", "2")
    _seed_company_books(conn, wayne, "Wayne Retail", "Wayne Gear", "5")


def _state(conn):
    """Every retailclaw_* row plus company and audit rows, PyPika-read."""
    out = {}
    for name in _STATE_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
        out[name] = sorted(
            json.dumps(dict(r), sort_keys=True, default=str) for r in rows)
    return out


def _action_ns(action, company_id=None, company_name=None):
    base = {"company_id": company_id, "company_name": company_name}
    if action == "retail-list-shrinkage":
        return ns(store_location_id=None, cause=None, limit=50, offset=0,
                  **base)
    if action == "retail-channel-performance":
        return ns(start_date=None, end_date=None, **base)
    if action == "retail-margin-analysis":
        return ns(limit=50, offset=0, **base)
    if action == "retail-loyalty-report":
        return ns(program_id=None, **base)
    if action == "retail-category-performance":
        return ns(limit=50, offset=0, **base)
    if action == "retail-promotion-effectiveness":
        return ns(promo_status=None, limit=50, offset=0, **base)
    if action == "retail-inventory-turnover":
        return ns(start_date=None, end_date=None, limit=50, offset=0,
                  **base)
    raise AssertionError(action)


def _zero_dict():
    return {"status": "error", "error": ZERO_COMPANY_ERROR,
            "message": ZERO_COMPANY_ERROR,
            "suggestion": ZERO_COMPANY_SUGGESTION}


def _multi_dict(acme, wayne):
    return {"status": "error", "error": MULTI_COMPANY_ERROR,
            "message": MULTI_COMPANY_ERROR,
            "companies": [{"id": acme, "name": ACME_NAME},
                          {"id": wayne, "name": WAYNE_NAME}],
            "suggestion": MULTI_COMPANY_SUGGESTION}


# ---------------------------------------------------------------------------
# 1. Zero companies refuse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_zero_companies_refuses(conn, action):
    """No company in the install: every list and report refuses with the
    exact zero-company dict and writes nothing."""
    before = _state(conn)
    result = call_action(_ACTION_FNS[action], conn, _action_ns(action))
    assert result == _zero_dict()
    assert _state(conn) == before


# ---------------------------------------------------------------------------
# 2. Two companies, no company: refuse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_two_companies_no_company_refuses(conn, action):
    """Two companies and no company given: every list and report refuses
    with the exact multiple-company dict and writes nothing."""
    acme, wayne = _seed_exact_companies(conn)
    _seed_both_books(conn, acme, wayne)
    before = _state(conn)
    result = call_action(_ACTION_FNS[action], conn, _action_ns(action))
    assert result == _multi_dict(acme, wayne)
    assert _state(conn) == before


# ---------------------------------------------------------------------------
# 3. Unknown company id refuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_unknown_company_refuses(conn, action):
    """An explicit company id that does not exist refuses (never an empty
    page) and writes nothing."""
    acme, wayne = _seed_exact_companies(conn)
    _seed_both_books(conn, acme, wayne)
    before = _state(conn)
    result = call_action(_ACTION_FNS[action], conn,
                         _action_ns(action, company_id="no-such-company"))
    assert result == {"status": "error",
                      "error": "Company not found: no-such-company",
                      "message": "Company not found: no-such-company"}
    assert _state(conn) == before


# ---------------------------------------------------------------------------
# 4. Explicit second company scopes
# ---------------------------------------------------------------------------

def test_explicit_second_company_scopes(conn):
    """The Wayne-scoped channel report names Wayne Retail, the category
    report names Wayne Gear, and the shrinkage list carries Wayne's
    quantity string."""
    acme, wayne = _seed_exact_companies(conn)
    _seed_both_books(conn, acme, wayne)
    channel = call_action(mod.retail_channel_performance, conn,
                          _action_ns("retail-channel-performance",
                                     company_id=wayne))
    assert is_ok(channel), channel
    assert channel["total_channels"] == 1
    assert [r["channel_name"] for r in channel["rows"]] == ["Wayne Retail"]
    category = call_action(mod.retail_category_performance, conn,
                           _action_ns("retail-category-performance",
                                      company_id=wayne))
    assert is_ok(category), category
    assert category["total_categories"] == 1
    assert [r["name"] for r in category["rows"]] == ["Wayne Gear"]
    shrinkage = call_action(mod.retail_list_shrinkage, conn,
                            _action_ns("retail-list-shrinkage",
                                       company_id=wayne))
    assert is_ok(shrinkage), shrinkage
    assert shrinkage["total_count"] == 1
    assert [r["quantity"] for r in shrinkage["shrinkage_records"]] == ["5"]


# ---------------------------------------------------------------------------
# 5. One company: no-company equals explicit (guard)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ALL_ACTIONS)
def test_one_company_uses_it(conn, action):
    """Guard: with a single company, omitting the company answers exactly
    as passing its id. This pins that single-company installs see no
    behaviour change."""
    acme = _seed_acme_only(conn)
    _seed_company_books(conn, acme, "Acme Retail", "Acme Tools", "2")
    implicit = call_action(_ACTION_FNS[action], conn, _action_ns(action))
    explicit = call_action(_ACTION_FNS[action], conn,
                           _action_ns(action, company_id=acme))
    assert is_ok(implicit), implicit
    assert implicit == explicit


# ---------------------------------------------------------------------------
# 6. --company flag resolution
# ---------------------------------------------------------------------------

def test_company_flag_resolves_name(conn):
    """_resolve_company_flag maps an exact case-insensitive name to its id,
    passes an id straight through, and refuses a miss before writing."""
    acme, wayne = _seed_exact_companies(conn)
    _seed_both_books(conn, acme, wayne)
    args = ns(company_id=None, company_name="acme widgets")
    mod._resolve_company_flag(conn, args)
    assert args.company_id == acme
    args_id = ns(company_id=None, company_name=acme)
    mod._resolve_company_flag(conn, args_id)
    assert args_id.company_id == acme
    before = _state(conn)
    result = call_action(mod._resolve_company_flag, conn,
                         ns(company_id=None, company_name="Acme"))
    assert result == {"status": "error",
                      "error": "Company 'Acme' not found.",
                      "message": "Company 'Acme' not found.",
                      "available_companies": [ACME_NAME, WAYNE_NAME],
                      "suggestion": NAME_MISS_SUGGESTION}
    assert _state(conn) == before
