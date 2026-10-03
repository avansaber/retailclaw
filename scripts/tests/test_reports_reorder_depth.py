"""Depth tests: effects on stored rows for four retailclaw actions.

Existing-test search (2026-09-17): no test in this directory references any of
  - retail-segment-performance-report
  - retail-set-location-reorder-point
  - retail-shrinkage-by-cause-report
  - retail-shrinkage-report
(the closest hit is the phrase "Location reorder points" in the module
docstring of test_locations_ecommerce.py, which covers other actions). The
nearest behavioural models read -- test_store_credit_behaviour.py and
test_gift_card_redeem_guard.py -- were followed for style: exact string money,
rows read back from the database, refusals pinned to message plus unchanged
tables.

Per-action depth signal:
  - retail-shrinkage-report: STORED ROW. Aggregates re-derived from the exact
    stored quantity/value_lost strings and compared cent-for-cent; the table
    and audit_log are unchanged (read-only report).
  - retail-shrinkage-by-cause-report: STORED ROW. Every incident grouped under
    its cause with exact stored values, including the store_name join; the
    table and audit_log are unchanged (read-only report).
  - retail-set-location-reorder-point: STORED ROW. retailclaw_planogram_item
    min_stock moves from its old value to the new one; every other column and
    every sibling row is unchanged. The no-mapping ("noted") path is pinned to
    write nothing.
  - retail-segment-performance-report: STORED ROW (fixed m655). Submitted
    sales_invoice rows aggregated per customer with exact Decimal sums; the
    table and audit_log are unchanged (read-only report).

Ledger note (applies to all four): none of these handlers posts to the GL --
no gl_entry inserts and no audit() calls -- so there are no debit/credit legs
to assert or balance. The audit_log-unchanged assertions are the standing
proof that no ledger-adjacent side effect occurred; do not add gl_entry
assertions for these actions.

FIXED m655: retail-segment-performance-report now filters submitted statuses
with DecimalSum and Decimal scoring; the behaviour test seeds submitted
invoices and asserts per-segment counts and exact total_revenue strings.
"""
import uuid
from decimal import Decimal

from retail_helpers import (
    call_action, is_error, is_ok, load_db_query, ns, seed_company,
)

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot(conn, tables):
    """Full ordered dumps of the given tables for before/after comparison."""
    snap = {}
    for table in tables:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        snap[table] = [tuple(row) for row in rows]
    return snap


def _audit_count(conn):
    return conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


def _record_shrinkage(conn, env, quantity, cause, value_lost, discovered_date,
                      store_location_id=None, item_id=None, company_id=None):
    return call_action(mod.retail_record_shrinkage, conn, ns(
        company_id=company_id or env["company_id"],
        store_location_id=store_location_id,
        item_id=item_id or env["item1"],
        quantity=quantity,
        cause=cause,
        discovered_date=discovered_date,
        reported_by="depth-probe",
        value_lost=value_lost,
        notes=None,
    ))


def _shrinkage_rows(conn, company_id):
    return conn.execute(
        "SELECT id, store_location_id, item_id, quantity, cause, "
        "discovered_date, reported_by, value_lost, notes, company_id "
        "FROM retailclaw_shrinkage WHERE company_id = ? "
        "ORDER BY discovered_date, id",
        (company_id,),
    ).fetchall()


def _shrinkage_count(conn):
    return conn.execute("SELECT COUNT(*) FROM retailclaw_shrinkage").fetchone()[0]


def _add_location(conn, env, name):
    result = call_action(mod.retail_add_store_location, conn, ns(
        company_id=env["company_id"],
        name=name,
        store_code=None,
        warehouse_id=None,
        address_line1=None,
        city=None,
        state=None,
        zip_code=None,
        store_type="retail",
        manager_name=None,
        phone=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_planogram(conn, env, store_section, name="Probe Planogram"):
    result = call_action(mod.retail_add_planogram, conn, ns(
        company_id=env["company_id"],
        name=name,
        description=None,
        store_section=store_section,
        fixture_type=None,
        shelf_count="1",
        width_inches=None,
        height_inches=None,
        effective_date=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _add_planogram_item(conn, planogram_id, item_id, item_name, min_stock,
                        max_stock="20", facings="2"):
    result = call_action(mod.retail_add_planogram_item, conn, ns(
        planogram_id=planogram_id,
        item_id=item_id,
        item_name=item_name,
        shelf_number="1",
        position="1",
        facings=facings,
        min_stock=min_stock,
        max_stock=max_stock,
        notes=None,
    ))
    assert is_ok(result), result
    return result["id"]


def _set_reorder_point(conn, store_location_id, item_id, min_stock):
    return call_action(mod.retail_set_location_reorder_point, conn, ns(
        store_location_id=store_location_id,
        item_id=item_id,
        min_stock=min_stock,
    ))


def _planogram_item(conn, planogram_item_id):
    return conn.execute(
        "SELECT planogram_id, item_id, shelf_number, position, facings, "
        "min_stock, max_stock FROM retailclaw_planogram_item WHERE id = ?",
        (planogram_item_id,),
    ).fetchone()


def _planogram_item_count(conn):
    return conn.execute(
        "SELECT COUNT(*) FROM retailclaw_planogram_item").fetchone()[0]


def _seed_invoice(conn, env, grand_total, posting_date, customer_id=None):
    """Direct foundation seed: no retail action owns sales_invoice."""
    invoice_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sales_invoice (id, customer_id, posting_date, "
        "grand_total, status, company_id) VALUES (?, ?, ?, ?, ?, ?)",
        (invoice_id, customer_id or env["customer_id"], posting_date,
         grand_total, "submitted", env["company_id"]),
    )
    conn.commit()
    return invoice_id


# ─────────────────────────────────────────────────────────────────────────────
# retail-shrinkage-report (stored-row signal; read-only, no ledger legs)
# ─────────────────────────────────────────────────────────────────────────────

class TestShrinkageReport:
    def test_totals_match_stored_rows_to_the_cent(self, conn, env):
        cid = env["company_id"]
        first = _record_shrinkage(conn, env, "3", "theft", "150.00", "2026-05-02")
        second = _record_shrinkage(conn, env, "2", "theft", "50.00", "2026-05-03")
        third = _record_shrinkage(conn, env, "1", "damage", "25.50", "2026-05-04")
        assert is_ok(first) and is_ok(second) and is_ok(third)
        other_company = seed_company(conn)
        assert is_ok(_record_shrinkage(
            conn, env, "9", "theft", "999.99", "2026-05-05",
            company_id=other_company))

        stored_before = [dict(r) for r in _shrinkage_rows(conn, cid)]
        assert [(r["quantity"], r["value_lost"], r["cause"]) for r in stored_before] == [
            ("3", "150.00", "theft"),
            ("2", "50.00", "theft"),
            ("1", "25.50", "damage"),
        ]
        audit_before = _audit_count(conn)

        result = call_action(mod.retail_shrinkage_report, conn, ns(company_id=cid))
        assert is_ok(result), result
        assert result["company_id"] == cid
        assert result["by_cause"] == [
            {"cause": "theft", "incident_count": 2,
             "total_quantity": "5.00", "total_value_lost": "200.00"},
            {"cause": "damage", "incident_count": 1,
             "total_quantity": "1.00", "total_value_lost": "25.50"},
        ]
        assert result["grand_total_quantity"] == "6.00"
        assert result["grand_total_value_lost"] == "225.50"

        reread = [dict(r) for r in _shrinkage_rows(conn, cid)]
        assert reread == stored_before
        assert sum((Decimal(r["quantity"]) for r in reread), Decimal("0")) == Decimal("6.00")
        assert sum((Decimal(r["value_lost"]) for r in reread), Decimal("0")) == Decimal("225.50")
        assert Decimal(result["grand_total_value_lost"]) == Decimal("225.50")
        assert _shrinkage_count(conn) == 4
        assert _audit_count(conn) == audit_before

    def test_empty_company_reports_zeroes(self, conn, env):
        empty_company = seed_company(conn)
        result = call_action(
            mod.retail_shrinkage_report, conn, ns(company_id=empty_company))
        assert is_ok(result), result
        assert result["by_cause"] == []
        assert result["grand_total_quantity"] == "0.00"
        assert result["grand_total_value_lost"] == "0.00"

    def test_refuses_missing_company_without_writing(self, conn, env):
        assert is_ok(_record_shrinkage(conn, env, "1", "theft", "10.00", "2026-05-06"))
        before = _snapshot(conn, ["retailclaw_shrinkage", "audit_log"])

        result = call_action(mod.retail_shrinkage_report, conn, ns(company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _snapshot(conn, ["retailclaw_shrinkage", "audit_log"]) == before

    def test_refuses_unknown_company_without_writing(self, conn, env):
        before = _snapshot(conn, ["retailclaw_shrinkage", "audit_log"])

        result = call_action(
            mod.retail_shrinkage_report, conn, ns(company_id="no-such-company"))
        assert is_error(result), result
        assert result["message"] == "Company no-such-company not found"
        assert _snapshot(conn, ["retailclaw_shrinkage", "audit_log"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-shrinkage-by-cause-report (stored-row signal; read-only, no ledger)
# ─────────────────────────────────────────────────────────────────────────────

class TestShrinkageByCauseReport:
    def test_groups_every_incident_with_exact_stored_values(self, conn, env):
        cid = env["company_id"]
        loc_id = _add_location(conn, env, "Downtown Probe")
        linked = _record_shrinkage(conn, env, "3", "theft", "150.00", "2026-05-02",
                                   store_location_id=loc_id)
        unlinked_theft = _record_shrinkage(conn, env, "2", "theft", "50.00", "2026-05-03")
        damaged = _record_shrinkage(conn, env, "1", "damage", "25.50", "2026-05-04")
        assert is_ok(linked) and is_ok(unlinked_theft) and is_ok(damaged)
        assert is_ok(_record_shrinkage(
            conn, env, "9", "theft", "999.99", "2026-05-05",
            company_id=seed_company(conn)))
        stored_before = [dict(r) for r in _shrinkage_rows(conn, cid)]
        audit_before = _audit_count(conn)

        result = call_action(
            mod.retail_shrinkage_by_cause_report, conn, ns(company_id=cid))
        assert is_ok(result), result
        assert result["company_id"] == cid
        assert result["total_incidents"] == 3
        assert set(result["by_cause"]) == {"theft", "damage"}
        assert result["by_cause"]["theft"]["count"] == 2
        assert result["by_cause"]["damage"]["count"] == 1

        by_id = {}
        for cause, group in result["by_cause"].items():
            for record in group["records"]:
                by_id[record["id"]] = record
        assert set(by_id) == {
            linked["shrinkage_id"], unlinked_theft["shrinkage_id"],
            damaged["shrinkage_id"],
        }
        assert (by_id[linked["shrinkage_id"]]["quantity"],
                by_id[linked["shrinkage_id"]]["value_lost"],
                by_id[linked["shrinkage_id"]]["cause"],
                by_id[linked["shrinkage_id"]]["discovered_date"],
                by_id[linked["shrinkage_id"]]["store_name"]) == (
            "3", "150.00", "theft", "2026-05-02", "Downtown Probe")
        assert (by_id[unlinked_theft["shrinkage_id"]]["quantity"],
                by_id[unlinked_theft["shrinkage_id"]]["value_lost"],
                by_id[unlinked_theft["shrinkage_id"]]["store_name"]) == (
            "2", "50.00", None)
        assert (by_id[damaged["shrinkage_id"]]["quantity"],
                by_id[damaged["shrinkage_id"]]["value_lost"],
                by_id[damaged["shrinkage_id"]]["cause"]) == (
            "1", "25.50", "damage")

        assert [dict(r) for r in _shrinkage_rows(conn, cid)] == stored_before
        assert _shrinkage_count(conn) == 4
        assert _audit_count(conn) == audit_before

    def test_refuses_missing_company_without_writing(self, conn, env):
        assert is_ok(_record_shrinkage(conn, env, "1", "damage", "5.00", "2026-05-06"))
        before = _snapshot(conn, ["retailclaw_shrinkage", "audit_log"])

        result = call_action(
            mod.retail_shrinkage_by_cause_report, conn, ns(company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _snapshot(conn, ["retailclaw_shrinkage", "audit_log"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-set-location-reorder-point (stored-row signal; no ledger legs)
# ─────────────────────────────────────────────────────────────────────────────

class TestSetLocationReorderPoint:
    def test_update_moves_min_stock_from_old_to_new(self, conn, env):
        loc_id = _add_location(conn, env, "Reorder Probe Store")
        plano_id = _add_planogram(conn, env, loc_id)
        target = _add_planogram_item(
            conn, plano_id, env["item1"], "Widget A", min_stock="2")
        sibling = _add_planogram_item(
            conn, plano_id, env["item2"], "Widget B", min_stock="4")

        before = _planogram_item(conn, target)
        assert before["min_stock"] == 2

        result = _set_reorder_point(conn, loc_id, env["item1"], "7")
        assert is_ok(result), result
        assert result["action"] == "updated"
        assert result["store_location_id"] == loc_id
        assert result["item_id"] == env["item1"]
        assert result["min_stock"] == 7

        after = _planogram_item(conn, target)
        assert after["min_stock"] == 7
        assert (after["planogram_id"], after["item_id"], after["shelf_number"],
                after["position"], after["facings"], after["max_stock"]) == (
            before["planogram_id"], before["item_id"], before["shelf_number"],
            before["position"], before["facings"], before["max_stock"])
        assert _planogram_item(conn, sibling)["min_stock"] == 4

    def test_noted_path_persists_nothing(self, conn, env):
        loc_id = _add_location(conn, env, "Planogram-less Store")
        items_before = _planogram_item_count(conn)
        audit_before = _audit_count(conn)

        result = _set_reorder_point(conn, loc_id, env["item1"], "9")
        assert is_ok(result), result
        assert result["action"] == "noted"
        assert result["min_stock"] == 9
        assert _planogram_item_count(conn) == items_before
        assert _audit_count(conn) == audit_before

    def test_refuses_negative_min_stock_without_writing(self, conn, env):
        loc_id = _add_location(conn, env, "Guarded Store")
        plano_id = _add_planogram(conn, env, loc_id)
        target = _add_planogram_item(
            conn, plano_id, env["item1"], "Widget A", min_stock="2")
        before = _snapshot(conn, ["retailclaw_planogram_item", "audit_log"])

        result = _set_reorder_point(conn, loc_id, env["item1"], "-3")
        assert is_error(result), result
        assert result["message"] == "--min-stock must be >= 0"
        assert _planogram_item(conn, target)["min_stock"] == 2
        assert _snapshot(conn, ["retailclaw_planogram_item", "audit_log"]) == before

    def test_refuses_unknown_location_without_writing(self, conn, env):
        before = _snapshot(conn, ["retailclaw_planogram_item",
                                  "retailclaw_store_location", "audit_log"])

        result = _set_reorder_point(conn, "location-that-does-not-exist",
                                    env["item1"], "5")
        assert is_error(result), result
        assert result["message"] == "Store location location-that-does-not-exist not found"
        assert _snapshot(conn, ["retailclaw_planogram_item",
                                "retailclaw_store_location", "audit_log"]) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-segment-performance-report: fixed m655 (submitted statuses, exact
# Decimal sums; read-only, no ledger legs)
# ─────────────────────────────────────────────────────────────────────────────

class TestSegmentPerformanceReport:
    def test_reports_seeded_segments_with_exact_money(self, conn, env):
        from datetime import date as _date

        today = _date.today().isoformat()
        _seed_invoice(conn, env, "6000.00", today)
        _seed_invoice(conn, env, "500.00", today)
        before = _snapshot(
            conn, ["sales_invoice", "retailclaw_shrinkage", "audit_log"])

        result = call_action(mod.retail_segment_performance_report, conn,
                             ns(company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["company_id"] == env["company_id"]
        assert result["segments"]["loyal"] == {
            "customer_count": 1, "total_revenue": "6500.00",
            "avg_frequency": "2.0",
        }
        for empty in ("champion", "potential", "at_risk", "dormant"):
            assert result["segments"][empty] == {
                "customer_count": 0, "total_revenue": "0.00",
                "avg_frequency": "0",
            }
        reread = conn.execute(
            "SELECT grand_total, status, company_id FROM sales_invoice "
            "WHERE company_id = ? ORDER BY grand_total",
            (env["company_id"],)).fetchall()
        assert [(r["grand_total"], r["status"]) for r in reread] == [
            ("500.00", "submitted"), ("6000.00", "submitted")]
        assert sum((Decimal(r["grand_total"]) for r in reread),
                   Decimal("0")) == Decimal("6500.00")
        assert _snapshot(
            conn, ["sales_invoice", "retailclaw_shrinkage", "audit_log"]) == before

    def test_refuses_missing_company_without_writing(self, conn, env):
        before = _snapshot(
            conn, ["sales_invoice", "retailclaw_shrinkage", "audit_log"])

        result = call_action(
            mod.retail_segment_performance_report, conn, ns(company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _snapshot(
            conn, ["sales_invoice", "retailclaw_shrinkage", "audit_log"]) == before
