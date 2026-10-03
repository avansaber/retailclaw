"""Depth tests for the 12 actions named in task m452-depth-retailclaw-1.

Each action gets at least one test that observes the DATABASE, not just the
response envelope:

- retail-add-store-shift            -> stored row (audit_log; no domain row)
- retail-auto-create-purchase-orders-> read-only suggestion (fixed m655)
- retail-calculate-rfm              -> read-only over sales_invoice (fixed m655)
- retail-category-performance       -> read-only over retailclaw_category
- retail-channel-performance        -> read-only over price lists + items
- retail-check-reorder-points       -> read-only over item + stock ledger (fixed m655)
- retail-check-store-credit-balance -> read-only over retailclaw_store_credit
- retail-fulfill-online-order       -> stored row (audit_log; order untouched)
- retail-generate-barcode-labels    -> read-only over item (BROKEN)
- retail-generate-purchase-suggestions -> read-only over item + ledger (fixed m655)
- retail-inventory-turnover         -> read-only over wholesale orders/items
- retail-issue-store-credit         -> stored row (retailclaw_store_credit)

None of these 12 actions reaches the ledger: no code path among them writes
gl_entry or journal_entry rows. Each writing test asserts the gl_entry count
is unchanged, and each read-only test asserts its snapshots are unchanged, so
a later reader does not add a balance assertion that cannot hold.

Money is text throughout: exact string equality plus Decimal equality.
No floating point and no approximation anywhere.

One action is BROKEN on this tree (it raises sqlite3.OperationalError
instead of answering): retail-generate-barcode-labels. Per the task it is NOT
fixed here: it gets a passing test documenting the real crash (including that
the crash writes nothing), an xfail test pinning the behaviour a fix must
produce, and a passing refusal test (refusals run before the broken SQL, so
they still work). The four procurement/RFM actions fixed in m655
(reorder points, purchase suggestions, auto-create purchase orders,
calculate RFM) keep a passing behaviour test plus a passing refusal test.
"""
import json
import sqlite3
import uuid
from datetime import date
from decimal import Decimal

import pytest

from retail_helpers import (
    call_action, ns, is_error, is_ok, load_db_query, seed_company,
)

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Snapshot helpers: prove what changed, what did not, and that refusals and
# crashes leave the database byte-identical within the tables an action can
# touch (its domain tables plus audit_log).
# ─────────────────────────────────────────────────────────────────────────────

def _dump(conn, tables):
    snap = {}
    for table in tables:
        rows = conn.execute("SELECT * FROM %s" % table).fetchall()
        snap[table] = sorted(
            json.dumps(dict(r), sort_keys=True, default=str) for r in rows)
    return snap


def _gl_count(conn):
    return conn.execute("SELECT COUNT(*) FROM gl_entry").fetchone()[0]


def _audit_action_rows(conn, action):
    return conn.execute(
        "SELECT skill, entity_type, entity_id, new_values FROM audit_log "
        "WHERE action = ?", (action,)).fetchall()


def _add_location(conn, env, name="Depth Store"):
    result = call_action(mod.retail_add_store_location, conn, ns(
        company_id=env["company_id"], name=name, store_code=None,
        warehouse_id=None, address_line1=None, city=None, state=None,
        zip_code=None, store_type="retail", manager_name=None, phone=None,
        location_status="active"))
    assert is_ok(result), result
    return result["id"]


# ─────────────────────────────────────────────────────────────────────────────
# retail-add-store-shift — STORED ROW (audit_log). Writes no domain row: the
# shift lives in the audit trail, the store_location row must be untouched.
# Does not reach the ledger.
# ─────────────────────────────────────────────────────────────────────────────

class TestAddStoreShift:
    TABLES = ["retailclaw_store_location", "audit_log"]

    def test_shift_writes_audit_and_leaves_store_untouched(self, conn, env):
        loc_id = _add_location(conn, env)
        before_store = dict(conn.execute(
            "SELECT * FROM retailclaw_store_location WHERE id = ?",
            (loc_id,)).fetchone())
        gl_before = _gl_count(conn)

        result = call_action(mod.retail_add_store_shift, conn, ns(
            company_id=env["company_id"], store_location_id=loc_id,
            name="Morning", start_date="2026-06-01", end_date="2026-06-02"))
        assert is_ok(result), result
        assert result["store_location_id"] == loc_id
        assert result["shift_name"] == "Morning"

        rows = _audit_action_rows(conn, "retail-add-store-shift")
        assert len(rows) == 1
        assert rows[0]["skill"] == "retailclaw"
        assert rows[0]["entity_type"] == "retailclaw_store_location"
        assert rows[0]["entity_id"] == loc_id
        assert json.loads(rows[0]["new_values"]) == {
            "shift_name": "Morning",
            "start_date": "2026-06-01", "end_date": "2026-06-02"}

        after_store = dict(conn.execute(
            "SELECT * FROM retailclaw_store_location WHERE id = ?",
            (loc_id,)).fetchone())
        assert after_store == before_store
        assert _gl_count(conn) == gl_before

    def test_shift_refuses_missing_location_id(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_add_store_shift, conn, ns(
            company_id=env["company_id"], store_location_id=None,
            name="Morning", start_date=None, end_date=None))
        assert is_error(result), result
        assert result["message"] == "--store-location-id is required"
        assert _dump(conn, self.TABLES) == before

    def test_shift_refuses_unknown_store(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_add_store_shift, conn, ns(
            company_id=env["company_id"], store_location_id="no-such-store",
            name="Morning", start_date=None, end_date=None))
        assert is_error(result), result
        assert result["message"] == "Store location no-such-store not found"
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-check-reorder-points — fixed m655: company-scoped exact-Decimal
# stock (shared catalog; per-warehouse sums with is_cancelled = 0).
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckReorderPoints:
    TABLES = ["item", "stock_ledger_entry", "audit_log"]

    def _seed_low_stock(self, conn, env):
        conn.execute(
            "UPDATE item SET reorder_level = '10', reorder_qty = '5', "
            "standard_rate = '2.50' WHERE id = ?", (env["item1"],))
        wid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO warehouse (id, name, company_id) VALUES (?, ?, ?)",
            (wid, "Depth WH", env["company_id"]))
        conn.execute(
            "INSERT INTO stock_ledger_entry (id, item_id, warehouse_id, "
            "posting_date, actual_qty, qty_after_transaction, "
            "valuation_rate, stock_value, stock_value_difference, "
            "voucher_type, voucher_id, is_cancelled) "
            "VALUES (?, ?, ?, '2026-02-01', '3', '3', '2.50', '7.50', "
            "'7.50', 'stock_entry', 'INIT-depth', 0)",
            (str(uuid.uuid4()), env["item1"], wid))
        conn.commit()

    def test_reports_seeded_low_stock_item(self, conn, env):
        self._seed_low_stock(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_check_reorder_points, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["items_below_reorder"] >= 1
        match = [i for i in result["items"]
                 if i["item_id"] == env["item1"]]
        assert len(match) == 1
        assert match[0]["reorder_level"] == "10"
        assert match[0]["current_stock"] == "3.00"
        assert match[0]["deficit"] == "7.00"
        assert Decimal(match[0]["current_stock"]) == Decimal("3.00")
        assert Decimal(match[0]["deficit"]) == Decimal("7.00")
        assert _dump(conn, self.TABLES) == before

    def test_refuses_missing_company(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_check_reorder_points, conn, ns(
            company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _dump(conn, self.TABLES) == before

    def test_ignores_other_company_stock_and_cancelled_rows(self, conn, env):
        self._seed_low_stock(conn, env)
        other_company = seed_company(conn)
        other_wid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO warehouse (id, name, company_id) VALUES (?, ?, ?)",
            (other_wid, "Other Co WH", other_company))
        conn.execute(
            "INSERT INTO stock_ledger_entry (id, item_id, warehouse_id, "
            "posting_date, actual_qty, qty_after_transaction, "
            "valuation_rate, stock_value, stock_value_difference, "
            "voucher_type, voucher_id, is_cancelled) "
            "VALUES (?, ?, ?, '2026-02-02', '50', '50', '2.50', '125.00', "
            "'125.00', 'stock_entry', 'INIT-other', 0)",
            (str(uuid.uuid4()), env["item1"], other_wid))
        own_wid = conn.execute(
            "SELECT id FROM warehouse WHERE company_id = ?",
            (env["company_id"],)).fetchone()["id"]
        conn.execute(
            "INSERT INTO stock_ledger_entry (id, item_id, warehouse_id, "
            "posting_date, actual_qty, qty_after_transaction, "
            "valuation_rate, stock_value, stock_value_difference, "
            "voucher_type, voucher_id, is_cancelled) "
            "VALUES (?, ?, ?, '2026-02-03', '20', '20', '2.50', '50.00', "
            "'50.00', 'stock_entry', 'INIT-cancelled', 1)",
            (str(uuid.uuid4()), env["item1"], own_wid))
        conn.commit()
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_check_reorder_points, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        match = [i for i in result["items"]
                 if i["item_id"] == env["item1"]]
        assert len(match) == 1
        assert match[0]["current_stock"] == "3.00"
        assert match[0]["deficit"] == "7.00"
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-generate-purchase-suggestions — fixed m655: company-scoped
# exact-Decimal stock (shared catalog; per-warehouse sums).
# ─────────────────────────────────────────────────────────────────────────────

class TestGeneratePurchaseSuggestions:
    TABLES = ["item", "stock_ledger_entry", "audit_log"]

    def _seed_low_stock(self, conn, env):
        conn.execute(
            "UPDATE item SET reorder_level = '10', reorder_qty = '5', "
            "standard_rate = '2.50' WHERE id = ?", (env["item1"],))
        wid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO warehouse (id, name, company_id) VALUES (?, ?, ?)",
            (wid, "Depth WH", env["company_id"]))
        conn.execute(
            "INSERT INTO stock_ledger_entry (id, item_id, warehouse_id, "
            "posting_date, actual_qty, qty_after_transaction, "
            "valuation_rate, stock_value, stock_value_difference, "
            "voucher_type, voucher_id, is_cancelled) "
            "VALUES (?, ?, ?, '2026-02-01', '3', '3', '2.50', '7.50', "
            "'7.50', 'stock_entry', 'INIT-depth', 0)",
            (str(uuid.uuid4()), env["item1"], wid))
        conn.commit()

    def test_suggests_seeded_reorder_with_exact_money(self, conn, env):
        self._seed_low_stock(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_generate_purchase_suggestions, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["suggestion_count"] == 1
        match = [s for s in result["suggestions"]
                 if s["item_id"] == env["item1"]]
        assert len(match) == 1
        assert match[0]["suggested_qty"] == "5"
        assert match[0]["estimated_cost"] == "12.50"
        assert Decimal(match[0]["estimated_cost"]) == Decimal("12.50")
        assert result["estimated_total_cost"] == "12.50"
        assert Decimal(result["estimated_total_cost"]) == Decimal("12.50")
        assert _dump(conn, self.TABLES) == before

    def test_refuses_missing_company(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_generate_purchase_suggestions, conn, ns(
            company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-auto-create-purchase-orders — fixed m655: company-scoped
# exact-Decimal stock with item_supplier priority grouping. By design it
# writes nothing (real POs belong to erpclaw-buying).
# ─────────────────────────────────────────────────────────────────────────────

class TestAutoCreatePurchaseOrders:
    TABLES = ["item", "stock_ledger_entry", "purchase_order",
              "purchase_order_item", "audit_log"]

    def _seed_low_stock(self, conn, env):
        conn.execute(
            "UPDATE item SET reorder_level = '10', reorder_qty = '5', "
            "standard_rate = '2.50' WHERE id = ?", (env["item1"],))
        wid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO warehouse (id, name, company_id) VALUES (?, ?, ?)",
            (wid, "Depth WH", env["company_id"]))
        conn.execute(
            "INSERT INTO stock_ledger_entry (id, item_id, warehouse_id, "
            "posting_date, actual_qty, qty_after_transaction, "
            "valuation_rate, stock_value, stock_value_difference, "
            "voucher_type, voucher_id, is_cancelled) "
            "VALUES (?, ?, ?, '2026-02-01', '3', '3', '2.50', '7.50', "
            "'7.50', 'stock_entry', 'INIT-depth', 0)",
            (str(uuid.uuid4()), env["item1"], wid))
        conn.commit()

    def test_groups_seeded_item_without_writing_pos(self, conn, env):
        self._seed_low_stock(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_auto_create_purchase_orders, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["purchase_order_groups"] >= 1
        flat = [i for g in result["groups"] for i in g["items"]]
        match = [i for i in flat if i["item_id"] == env["item1"]]
        assert len(match) == 1
        assert match[0]["qty"] == "5"
        assert Decimal(match[0]["rate"]) == Decimal("2.50")
        assert _dump(conn, self.TABLES) == before

    def test_refuses_missing_company(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_auto_create_purchase_orders, conn, ns(
            company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _dump(conn, self.TABLES) == before

    def test_groups_by_lowest_priority_supplier_without_writing(self, conn, env):
        self._seed_low_stock(conn, env)
        sup_b = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO supplier (id, name, company_id) VALUES (?, ?, ?)",
            (sup_b, "Depth Supplier B", env["company_id"]))
        sup_c = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO supplier (id, name, company_id) VALUES (?, ?, ?)",
            (sup_c, "Depth Supplier C", env["company_id"]))
        conn.execute(
            "INSERT INTO item_supplier (id, item_id, supplier_id, priority) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), env["item1"], sup_b, 2))
        conn.execute(
            "INSERT INTO item_supplier (id, item_id, supplier_id, priority) "
            "VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), env["item1"], sup_c, 1))
        conn.commit()
        before = _dump(conn, self.TABLES)
        po_before = conn.execute(
            "SELECT COUNT(*) FROM purchase_order").fetchone()[0]
        poi_before = conn.execute(
            "SELECT COUNT(*) FROM purchase_order_item").fetchone()[0]
        result = call_action(mod.retail_auto_create_purchase_orders, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["purchase_order_groups"] == 1
        assert len(result["groups"]) == 1
        assert result["groups"][0]["supplier_id"] == sup_c
        assert len(result["groups"][0]["items"]) == 1
        assert result["groups"][0]["items"][0]["item_id"] == env["item1"]
        assert result["groups"][0]["items"][0]["qty"] == "5"
        assert result["groups"][0]["items"][0]["rate"] == "2.50"
        assert Decimal(result["groups"][0]["items"][0]["rate"]) == Decimal("2.50")
        assert conn.execute(
            "SELECT COUNT(*) FROM purchase_order").fetchone()[0] == po_before
        assert conn.execute(
            "SELECT COUNT(*) FROM purchase_order_item").fetchone()[0] == poi_before
        assert _dump(conn, self.TABLES) == before

    def test_unassigned_when_no_supplier_link(self, conn, env):
        self._seed_low_stock(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_auto_create_purchase_orders, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["purchase_order_groups"] == 1
        assert len(result["groups"]) == 1
        assert result["groups"][0]["supplier_id"] == "unassigned"
        assert len(result["groups"][0]["items"]) == 1
        assert result["groups"][0]["items"][0]["item_id"] == env["item1"]
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-generate-barcode-labels — BROKEN: filters on i.company_id, which does
# not exist on item. Documented, not fixed.
# ─────────────────────────────────────────────────────────────────────────────

class TestGenerateBarcodeLabels:
    TABLES = ["item", "audit_log"]

    def _seed_labelled_item(self, conn, env):
        conn.execute(
            "UPDATE item SET item_name = 'Depth Label Widget', "
            "barcode = '8901234567890', standard_rate = '19.99' "
            "WHERE id = ?", (env["item1"],))
        conn.commit()

    @pytest.mark.xfail(
        reason="BROKEN: i.company_id missing on item; a fix must return the "
               "seeded label with the exact stored price",
        strict=False)
    def test_returns_seeded_label_with_exact_price(self, conn, env):
        self._seed_labelled_item(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_generate_barcode_labels, conn, ns(
            company_id=env["company_id"], search="Depth Label",
            category_id=None, limit=50))
        assert is_ok(result), result
        assert result["label_count"] >= 1
        match = [label for label in result["labels"]
                 if label["item_id"] == env["item1"]]
        assert len(match) == 1
        assert match[0]["sku"] == conn.execute(
            "SELECT item_code FROM item WHERE id = ?",
            (env["item1"],)).fetchone()["item_code"]
        assert match[0]["upc"] == "8901234567890"
        assert match[0]["price"] == "19.99"
        assert Decimal(match[0]["price"]) == Decimal("19.99")
        assert _dump(conn, self.TABLES) == before

    def test_documents_crash_and_writes_nothing(self, conn, env):
        self._seed_labelled_item(conn, env)
        before = _dump(conn, self.TABLES)
        with pytest.raises(sqlite3.OperationalError):
            call_action(mod.retail_generate_barcode_labels, conn, ns(
                company_id=env["company_id"], search=None,
                category_id=None, limit=50))
        assert _dump(conn, self.TABLES) == before

    def test_refuses_missing_company(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_generate_barcode_labels, conn, ns(
            company_id=None, search=None, category_id=None, limit=50))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-calculate-rfm — fixed m655: submitted statuses with DecimalSum and
# Decimal scoring (no float).
# ─────────────────────────────────────────────────────────────────────────────

class TestCalculateRfm:
    TABLES = ["sales_invoice", "customer", "audit_log"]

    def _seed_invoices(self, conn, env):
        today = date.today().isoformat()
        conn.execute(
            "INSERT INTO sales_invoice (id, customer_id, posting_date, "
            "grand_total, status, company_id) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), env["customer_id"], today,
             "6000.00", "submitted", env["company_id"]))
        conn.execute(
            "INSERT INTO sales_invoice (id, customer_id, posting_date, "
            "grand_total, status, company_id) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), env["customer_id"], today,
             "500.00", "submitted", env["company_id"]))
        conn.commit()

    def test_segments_seeded_customer_with_exact_money(self, conn, env):
        self._seed_invoices(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_calculate_rfm, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["customer_count"] >= 1
        match = [s for s in result["segments"]
                 if s["customer_id"] == env["customer_id"]]
        assert len(match) == 1
        assert match[0]["frequency"] == 2
        assert match[0]["monetary"] == "6500.00"
        assert Decimal(match[0]["monetary"]) == Decimal("6500.00")
        assert match[0]["recency_days"] == 0
        assert _dump(conn, self.TABLES) == before

    def test_refuses_missing_company(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_calculate_rfm, conn, ns(
            company_id=None))
        assert is_error(result), result
        assert result["message"] == "--company-id is required"
        assert _dump(conn, self.TABLES) == before

    def test_submitted_statuses_count_with_exact_money(self, conn, env):
        today = date.today().isoformat()
        for grand_total, status in [
            ("6000.00", "submitted"),
            ("500.00", "paid"),
            ("99.00", "draft"),
            ("77.00", "cancelled"),
        ]:
            conn.execute(
                "INSERT INTO sales_invoice (id, customer_id, posting_date, "
                "grand_total, status, company_id) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), env["customer_id"], today,
                 grand_total, status, env["company_id"]))
        conn.commit()
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_calculate_rfm, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(result), result
        assert result["customer_count"] == 1
        match = [s for s in result["segments"]
                 if s["customer_id"] == env["customer_id"]]
        assert len(match) == 1
        assert match[0]["frequency"] == 2
        assert match[0]["monetary"] == "6500.00"
        assert Decimal(match[0]["monetary"]) == Decimal("6500.00")
        assert match[0]["recency_days"] == 0
        assert match[0]["segment"] == "loyal"
        assert match[0]["r_score"] == 5
        assert match[0]["f_score"] == 2
        assert match[0]["m_score"] == 4
        assert match[0]["rfm_total"] == 11
        assert _dump(conn, self.TABLES) == before
        listed = call_action(mod.retail_list_customer_segments, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(listed), listed
        assert listed["total_customers"] == 1
        assert listed["segments"] == {
            "champion": 0, "loyal": 1, "potential": 0,
            "at_risk": 0, "dormant": 0,
        }
        assert _dump(conn, self.TABLES) == before
        perf = call_action(mod.retail_segment_performance_report, conn, ns(
            company_id=env["company_id"]))
        assert is_ok(perf), perf
        assert perf["segments"]["loyal"] == {
            "customer_count": 1, "total_revenue": "6500.00",
            "avg_frequency": "2.0",
        }
        for empty in ("champion", "potential", "at_risk", "dormant"):
            assert perf["segments"][empty] == {
                "customer_count": 0, "total_revenue": "0.00",
                "avg_frequency": "0",
            }
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-category-performance — READ-ONLY over retailclaw_category. No money
# in this report (counts only), so there is no monetary assertion to make;
# saying so here keeps a later reader from adding one that cannot hold.
# Does not reach the ledger.
# ─────────────────────────────────────────────────────────────────────────────

class TestCategoryPerformance:
    TABLES = ["retailclaw_category", "audit_log"]

    def _seed_categories(self, conn, env):
        parent = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"], name="Depth Parent",
            parent_id=None, description=None, sort_order=1))
        assert is_ok(parent), parent
        child = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"], name="Depth Child",
            parent_id=parent["id"], description=None, sort_order=2))
        assert is_ok(child), child
        return parent["id"], child["id"]

    def test_report_reflects_seeded_categories_exactly(self, conn, env):
        parent_id, child_id = self._seed_categories(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_category_performance, conn, ns(
            company_id=env["company_id"], limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_categories"] == 2
        by_id = {r["category_id"]: r for r in result["rows"]}
        assert by_id[parent_id]["name"] == "Depth Parent"
        assert by_id[parent_id]["parent_id"] is None
        assert by_id[parent_id]["subcategory_count"] == 1
        assert by_id[child_id]["name"] == "Depth Child"
        assert by_id[child_id]["parent_id"] == parent_id
        assert by_id[child_id]["subcategory_count"] == 0
        stored = {r["id"]: r["name"] for r in conn.execute(
            "SELECT id, name FROM retailclaw_category").fetchall()}
        assert set(by_id) == set(stored)
        assert _dump(conn, self.TABLES) == before

    def test_unknown_company_refuses_truthfully(self, conn, env):
        self._seed_categories(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_category_performance, conn, ns(
            company_id="no-such-company", limit=50, offset=0))
        assert result == {"status": "error",
                          "error": "Company not found: no-such-company",
                          "message": "Company not found: no-such-company"}, result
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-channel-performance — READ-ONLY over retailclaw_price_list and
# retailclaw_price_list_item. Money asserted as exact strings.
# Does not reach the ledger.
# ─────────────────────────────────────────────────────────────────────────────

class TestChannelPerformance:
    TABLES = ["retailclaw_price_list", "retailclaw_price_list_item",
              "audit_log"]

    def _seed_channel(self, conn, env):
        price_list = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"], name="Depth Channel",
            description=None, price_list_type="selling", currency="USD",
            is_default="1", valid_from=None, valid_to=None))
        assert is_ok(price_list), price_list
        for item_id, rate in ((env["item1"], "10.00"), (env["item2"], "20.00")):
            added = call_action(mod.retail_add_price_list_item, conn, ns(
                price_list_id=price_list["id"], item_id=item_id,
                item_name=None, rate=rate, min_qty="1", currency="USD",
                valid_from=None, valid_to=None))
            assert is_ok(added), added
        return price_list["id"]

    def test_report_sums_seeded_rates_as_exact_money(self, conn, env):
        self._seed_channel(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_channel_performance, conn, ns(
            company_id=env["company_id"], start_date=None, end_date=None))
        assert is_ok(result), result
        assert result["total_channels"] == 1
        row = result["rows"][0]
        assert row["channel_name"] == "Depth Channel"
        assert row["price_list_type"] == "selling"
        assert row["item_count"] == 2
        assert row["total_value"] == "30.00"
        assert Decimal(row["total_value"]) == Decimal("30.00")
        stored_sum = conn.execute(
            "SELECT SUM(CAST(rate AS NUMERIC)) AS total "
            "FROM retailclaw_price_list_item").fetchone()["total"]
        assert Decimal(str(stored_sum)) == Decimal(row["total_value"])
        assert _dump(conn, self.TABLES) == before

    def test_unknown_company_refuses_truthfully(self, conn, env):
        self._seed_channel(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_channel_performance, conn, ns(
            company_id="no-such-company", start_date=None, end_date=None))
        assert result == {"status": "error",
                          "error": "Company not found: no-such-company",
                          "message": "Company not found: no-such-company"}, result
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-inventory-turnover — READ-ONLY over retailclaw_wholesale_order and
# retailclaw_wholesale_order_item. Cancelled orders must not count.
# Money asserted as exact strings. Does not reach the ledger.
# ─────────────────────────────────────────────────────────────────────────────

class TestInventoryTurnover:
    TABLES = ["retailclaw_wholesale_customer", "retailclaw_wholesale_order",
              "retailclaw_wholesale_order_item", "audit_log"]

    def _seed_orders(self, conn, env):
        customer = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"], customer_id=None,
            business_name="Depth Distributors", contact_name=None,
            email=None, phone=None, tax_id=None, credit_limit=None,
            payment_terms=None, discount_pct=None, address_line1=None,
            address_line2=None, city=None, state=None, zip_code=None))
        assert is_ok(customer), customer
        order = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=customer["id"], order_date="2026-04-01",
            expected_delivery_date=None, notes=None))
        assert is_ok(order), order
        for item_name, qty, rate in (("Turn-A", 2, "15.00"),
                                     ("Turn-B", 1, "5.00")):
            added = call_action(mod.retail_add_wholesale_order_item, conn, ns(
                wholesale_order_id=order["id"], item_id=None,
                item_name=item_name, qty=qty, rate=rate, notes=None))
            assert is_ok(added), added
        cancelled = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=customer["id"], order_date="2026-04-02",
            expected_delivery_date=None, notes=None))
        assert is_ok(cancelled), cancelled
        excluded = call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=cancelled["id"], item_id=None,
            item_name="Turn-A", qty=100, rate="15.00", notes=None))
        assert is_ok(excluded), excluded
        conn.execute(
            "UPDATE retailclaw_wholesale_order SET order_status = 'cancelled' "
            "WHERE id = ?", (cancelled["id"],))
        conn.commit()

    def test_report_reflects_seeded_orders_and_skips_cancelled(self, conn, env):
        self._seed_orders(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_inventory_turnover, conn, ns(
            company_id=env["company_id"], start_date=None, end_date=None,
            limit=50, offset=0))
        assert is_ok(result), result
        assert result["total_items"] == 2
        by_name = {r["item_name"]: r for r in result["rows"]}
        assert by_name["Turn-A"]["total_qty"] == 2
        assert by_name["Turn-A"]["total_amount"] == "30.00"
        assert Decimal(by_name["Turn-A"]["total_amount"]) == Decimal("30.00")
        assert by_name["Turn-A"]["order_count"] == 1
        assert by_name["Turn-B"]["total_qty"] == 1
        assert by_name["Turn-B"]["total_amount"] == "5.00"
        assert Decimal(by_name["Turn-B"]["total_amount"]) == Decimal("5.00")
        stored = conn.execute(
            "SELECT amount FROM retailclaw_wholesale_order_item woi "
            "JOIN retailclaw_wholesale_order wo ON wo.id = woi.order_id "
            "WHERE wo.order_status != 'cancelled'").fetchall()
        assert sum((Decimal(r["amount"]) for r in stored),
                   Decimal("0")) == Decimal("35.00")
        assert _dump(conn, self.TABLES) == before

    def test_unknown_company_refuses_truthfully(self, conn, env):
        self._seed_orders(conn, env)
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_inventory_turnover, conn, ns(
            company_id="no-such-company", start_date=None, end_date=None,
            limit=50, offset=0))
        assert result == {"status": "error",
                          "error": "Company not found: no-such-company",
                          "message": "Company not found: no-such-company"}, result
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-issue-store-credit — STORED ROW (retailclaw_store_credit plus its
# audit row). Store credit never posts to the ledger, so a balance assertion
# cannot hold; the gl_entry count is pinned unchanged instead.
# ─────────────────────────────────────────────────────────────────────────────

class TestIssueStoreCredit:
    TABLES = ["retailclaw_store_credit", "audit_log"]

    def test_issue_stores_row_with_exact_money(self, conn, env):
        gl_before = _gl_count(conn)
        result = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount="250.00", source="return", reference_id=None,
            expiration_date=None))
        assert is_ok(result), result
        assert result["amount"] == "250.00"
        assert result["credit_status"] == "active"
        assert Decimal(result["amount"]) == Decimal("250.00")

        row = conn.execute(
            "SELECT customer_id, company_id, original_amount, "
            "remaining_balance, issued_date, source, status "
            "FROM retailclaw_store_credit WHERE id = ?",
            (result["store_credit_id"],)).fetchone()
        assert row["customer_id"] == env["customer_id"]
        assert row["company_id"] == env["company_id"]
        assert row["original_amount"] == "250.00"
        assert row["remaining_balance"] == "250.00"
        assert row["issued_date"] == date.today().isoformat()
        assert row["source"] == "return"
        assert row["status"] == "active"
        assert Decimal(row["original_amount"]) == Decimal("250.00")
        assert Decimal(row["remaining_balance"]) == Decimal("250.00")

        audits = _audit_action_rows(conn, "retail-issue-store-credit")
        assert len(audits) == 1
        assert (audits[0]["entity_type"],
                audits[0]["entity_id"]) == ("retailclaw_store_credit",
                                            result["store_credit_id"])
        assert _gl_count(conn) == gl_before

    def test_issue_refuses_zero_amount_without_writing(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount="0", source="return", reference_id=None,
            expiration_date=None))
        assert is_error(result), result
        assert result["message"] == "--amount must be greater than zero"
        assert _dump(conn, self.TABLES) == before

    def test_issue_refuses_bad_source_without_writing(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount="10.00", source="bonus", reference_id=None,
            expiration_date=None))
        assert is_error(result), result
        assert result["message"] == (
            "Invalid source: bonus. "
            "Must be one of: return, promotion, adjustment, gift")
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-check-store-credit-balance — READ-ONLY over retailclaw_store_credit:
# the response must match the stored rows to the cent, and the check itself
# must write nothing (no audit row, no ledger row).
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckStoreCreditBalance:
    TABLES = ["retailclaw_store_credit", "audit_log"]

    def _issue(self, conn, env, amount, source="return"):
        result = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount=amount, source=source, reference_id=None,
            expiration_date=None))
        assert is_ok(result), result
        return result["store_credit_id"]

    def test_balance_matches_stored_rows_to_the_cent(self, conn, env):
        first = self._issue(conn, env, "100.00")
        second = self._issue(conn, env, "25.50", source="gift")
        assert is_ok(call_action(mod.retail_redeem_store_credit, conn, ns(
            store_credit_id=first, amount="10.00")))
        before = _dump(conn, self.TABLES)
        gl_before = _gl_count(conn)

        result = call_action(mod.retail_check_store_credit_balance, conn, ns(
            customer_id=env["customer_id"]))
        assert is_ok(result), result
        assert result["active_credits"] == 2
        assert result["total_balance"] == "115.50"
        assert Decimal(result["total_balance"]) == Decimal("115.50")
        assert {(c["id"], c["remaining_balance"]) for c in result["credits"]} == {
            (first, "90.00"), (second, "25.50")}

        stored = conn.execute(
            "SELECT id, remaining_balance FROM retailclaw_store_credit "
            "WHERE customer_id = ? AND status = 'active'",
            (env["customer_id"],)).fetchall()
        assert {(r["id"], r["remaining_balance"]) for r in stored} == {
            (first, "90.00"), (second, "25.50")}
        assert sum((Decimal(r["remaining_balance"]) for r in stored),
                   Decimal("0")) == Decimal(result["total_balance"])
        assert _dump(conn, self.TABLES) == before
        assert _gl_count(conn) == gl_before

    def test_balance_refuses_missing_customer_without_writing(self, conn, env):
        self._issue(conn, env, "10.00")
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_check_store_credit_balance, conn, ns(
            customer_id=None))
        assert is_error(result), result
        assert result["message"] == "--customer-id is required"
        assert _dump(conn, self.TABLES) == before


# ─────────────────────────────────────────────────────────────────────────────
# retail-fulfill-online-order — STORED ROW (audit_log only). The sales_order
# row itself is byte-identical afterwards: the cross-skill status update is
# swallowed by `except Exception: pass`, so fulfillment is recorded, not
# applied. Does not reach the ledger.
#
# The audit row names the record: skill='retailclaw',
# action='retail-fulfill-online-order', entity_type='sales_order',
# entity_id=<order id>, with the tracking payload in new_values.
# ─────────────────────────────────────────────────────────────────────────────

class TestFulfillOnlineOrder:
    TABLES = ["sales_order", "audit_log"]

    def _seed_order(self, conn, env, status="draft"):
        order_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO sales_order (id, customer_id, order_date, status, "
            "company_id) VALUES (?, ?, '2026-03-01', ?, ?)",
            (order_id, env["customer_id"], status, env["company_id"]))
        conn.commit()
        return order_id

    def test_fulfill_records_audit_and_leaves_order_untouched(self, conn, env):
        order_id = self._seed_order(conn, env)
        before_order = dict(conn.execute(
            "SELECT * FROM sales_order WHERE id = ?", (order_id,)).fetchone())
        gl_before = _gl_count(conn)

        result = call_action(mod.retail_fulfill_online_order, conn, ns(
            company_id=env["company_id"], order_id=order_id,
            tracking_number="TRK-1", carrier="UPS"))
        assert is_ok(result), result
        assert result["order_id"] == order_id
        assert result["fulfillment_status"] == "fulfilled"
        assert result["tracking_number"] == "TRK-1"
        assert result["carrier"] == "UPS"

        rows = _audit_action_rows(conn, "retail-fulfill-online-order")
        assert len(rows) == 1
        assert rows[0]["skill"] == "retailclaw"
        assert rows[0]["entity_type"] == "sales_order"
        assert rows[0]["entity_id"] == order_id
        # The tracking payload is stored in new_values keyed by the order id.
        assert json.loads(rows[0]["new_values"]) == {
            "tracking": "TRK-1", "carrier": "UPS"}

        after_order = dict(conn.execute(
            "SELECT * FROM sales_order WHERE id = ?", (order_id,)).fetchone())
        assert after_order == before_order
        assert after_order["status"] == "draft"
        assert _gl_count(conn) == gl_before

    def test_fulfill_refuses_missing_order_id_without_writing(self, conn, env):
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_fulfill_online_order, conn, ns(
            company_id=env["company_id"], order_id=None,
            tracking_number="TRK-1", carrier="UPS"))
        assert is_error(result), result
        assert result["message"] == (
            "--order-id is required (wholesale-order-id or sales order id)")
        assert _dump(conn, self.TABLES) == before

    def test_fulfill_refuses_cancelled_order_without_writing(self, conn, env):
        order_id = self._seed_order(conn, env, status="cancelled")
        before = _dump(conn, self.TABLES)
        result = call_action(mod.retail_fulfill_online_order, conn, ns(
            company_id=env["company_id"], order_id=order_id,
            tracking_number="TRK-1", carrier="UPS"))
        assert is_error(result), result
        assert result["message"] == "Cannot fulfill cancelled order"
        assert _dump(conn, self.TABLES) == before
