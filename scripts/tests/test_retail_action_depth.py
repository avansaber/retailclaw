"""Behavioural depth tests for 12 retailclaw actions (m453-depth-retailclaw-2).

Each action below already had a test, but those tests prove the response
envelope (shape) or routability only: they never observe the database. Every
test here reads the effect back from the database through PyPika-built queries
(erpclaw_lib.query) and compares exact values. Money is compared as exact
Decimal strings, never float.

Signal per action (stored row vs ledger effect):
- retail-list-customer-segments .... stored rows in sales_invoice (read-only
  segment counts with exact Decimal sums; fixed m655).
- retail-list-inter-store-transfers  no signal: always returns empty even with
  transfer rows present (DEFECT documented, not fixed).
- retail-list-shrinkage ............ stored rows in retailclaw_shrinkage.
- retail-list-store-schedules ...... stored rows in retailclaw_store_location.
- retail-loyalty-report ............ stored rows in retailclaw_loyalty_member
  and retailclaw_loyalty_transaction (points are counts, asserted as ints).
- retail-margin-analysis ........... stored rows in retailclaw_price_list_item
  and retailclaw_wholesale_price.
- retail-omnichannel-sales-report .. stored rows in retailclaw_store_location,
  retailclaw_price_list(_item) and retailclaw_wholesale_order.
- retail-procurement-report ........ stored rows in item + stock_ledger_entry
  (read-only counts with exact Decimal stock; fixed m655).
- retail-promotion-effectiveness ... stored rows in retailclaw_promotion.
- retail-record-shrinkage .......... stored row in retailclaw_shrinkage plus
  one audit_log row.
- retail-redeem-store-credit ....... stored row change in
  retailclaw_store_credit plus audit_log rows.
- retail-request-inter-store-transfer  audit_log row only; persists no
  stock_entry, stock_ledger_entry or gl_entry row (documented, not fixed).

Ledger note for all twelve: none of these actions posts to gl_entry. Each
write-action test asserts gl_entry stays empty so a later reader does not add
a both-legs assertion that cannot hold.

No production file is touched by this module. Defects found are documented in
failing-expectation form where possible, otherwise pinned as observed.
"""
import json
from decimal import Decimal

from retail_helpers import (
    call_action, ns, is_error, is_ok, load_db_query, seed_customer,
)
from erpclaw_lib.query import Q, P, Table, Field, Order, fn, insert_row, dynamic_update

mod = load_db_query()

SNAPSHOT_TABLES = [
    "retailclaw_shrinkage",
    "retailclaw_store_location",
    "retailclaw_loyalty_program",
    "retailclaw_loyalty_member",
    "retailclaw_loyalty_transaction",
    "retailclaw_price_list",
    "retailclaw_price_list_item",
    "retailclaw_promotion",
    "retailclaw_wholesale_customer",
    "retailclaw_wholesale_price",
    "retailclaw_wholesale_order",
    "retailclaw_wholesale_order_item",
    "retailclaw_store_credit",
    "audit_log",
    "gl_entry",
    "stock_entry",
    "stock_entry_item",
    "stock_ledger_entry",
    "sales_invoice",
    "sales_order",
]


def _snapshot(conn):
    snap = {}
    for name in SNAPSHOT_TABLES:
        t = Table(name)
        rows = conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()
        snap[name] = sorted(
            tuple("" if v is None else str(v) for v in r) for r in rows
        )
    return snap


def _one(conn, table, col, val):
    t = Table(table)
    return conn.execute(
        Q.from_(t).select(t.star).where(Field(col) == P()).get_sql(), (val,)
    ).fetchone()


def _all(conn, table):
    t = Table(table)
    return conn.execute(Q.from_(t).select(t.star).get_sql()).fetchall()


def _count(conn, table):
    t = Table(table)
    return conn.execute(Q.from_(t).select(fn.Count("*")).get_sql()).fetchone()[0]


def _add_location(conn, env, name, store_type="retail"):
    r = call_action(mod.retail_add_store_location, conn, ns(
        company_id=env["company_id"], name=name, store_code=None,
        warehouse_id=None, address_line1=None, city=None, state=None,
        zip_code=None, store_type=store_type, manager_name=None, phone=None,
    ))
    assert is_ok(r), r
    return r["id"]


def _add_price_list(conn, env, name="Selling"):
    r = call_action(mod.retail_add_price_list, conn, ns(
        company_id=env["company_id"], name=name, description=None,
        price_list_type="selling", currency="USD", is_default=None,
        valid_from=None, valid_to=None,
    ))
    assert is_ok(r), r
    return r["id"]


def _add_price_list_item(conn, pl_id, item_id, item_name, rate):
    r = call_action(mod.retail_add_price_list_item, conn, ns(
        price_list_id=pl_id, item_id=item_id, item_name=item_name, rate=rate,
        min_qty=None, currency=None, valid_from=None, valid_to=None,
    ))
    assert is_ok(r), r
    return r["id"]


def _add_promotion(conn, env, name, promo_type, discount, max_uses=None):
    r = call_action(mod.retail_add_promotion, conn, ns(
        company_id=env["company_id"], name=name, description=None,
        promo_type=promo_type, discount_value=discount, min_purchase=None,
        max_discount=None, max_uses=max_uses, applicable_items=None,
        applicable_categories=None, start_date="2026-06-01",
        end_date="2026-08-31",
    ))
    assert is_ok(r), r
    return r["id"]


def _add_program(conn, env, name="Rewards"):
    r = call_action(mod.retail_add_loyalty_program, conn, ns(
        company_id=env["company_id"], name=name, description=None,
        points_per_dollar=None, redemption_rate=None, tiers=None,
    ))
    assert is_ok(r), r
    return r["id"]


def _add_member(conn, env, program_id, customer_name, tier=None):
    r = call_action(mod.retail_add_loyalty_member, conn, ns(
        company_id=env["company_id"], program_id=program_id,
        customer_id=None, customer_name=customer_name, email=None, phone=None,
        member_tier=tier, enrollment_date="2026-01-15",
    ))
    assert is_ok(r), r
    return r["id"]


def _seed_sales_invoice(conn, env, customer_id, posting_date, grand_total,
                        status="submitted"):
    import uuid
    inv_id = str(uuid.uuid4())
    sql, _ = insert_row("sales_invoice", {
        "id": P(), "customer_id": P(), "posting_date": P(),
        "grand_total": P(), "status": P(), "company_id": P(),
    })
    conn.execute(sql, (inv_id, customer_id, posting_date, grand_total,
                       status, env["company_id"]))
    conn.commit()
    return inv_id


def _seed_stock_entry(conn, env, entry_type="material_transfer",
                      status="submitted"):
    import uuid
    se_id = str(uuid.uuid4())
    sql, _ = insert_row("stock_entry", {
        "id": P(), "stock_entry_type": P(), "posting_date": P(),
        "company_id": P(), "status": P(),
    })
    conn.execute(sql, (se_id, entry_type, "2026-09-01", env["company_id"],
                       status))
    conn.commit()
    return se_id


class TestRecordShrinkage:
    def test_record_persists_exact_row_and_audit(self, conn, env):
        loc = _add_location(conn, env, "Downtown")
        before_gl = _count(conn, "gl_entry")
        before_sle = _count(conn, "stock_ledger_entry")
        r = call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item1"], quantity="2.50", cause="damage",
            discovered_date="2026-09-01", reported_by="J. Doe",
            value_lost="19.99", notes="cracked lens",
        ))
        assert is_ok(r), r
        sid = r["shrinkage_id"]
        assert r["quantity"] == "2.50"
        assert r["value_lost"] == "19.99"
        row = _one(conn, "retailclaw_shrinkage", "id", sid)
        assert row["store_location_id"] == loc
        assert row["item_id"] == env["item1"]
        assert row["quantity"] == "2.50"
        assert Decimal(row["quantity"]) == Decimal("2.50")
        assert row["cause"] == "damage"
        assert row["discovered_date"] == "2026-09-01"
        assert row["reported_by"] == "J. Doe"
        assert row["value_lost"] == "19.99"
        assert Decimal(row["value_lost"]) == Decimal("19.99")
        assert row["notes"] == "cracked lens"
        assert row["company_id"] == env["company_id"]
        audits = [dict(a) for a in _all(conn, "audit_log")
                  if a["action"] == "retail-record-shrinkage"]
        assert len(audits) == 1
        assert audits[0]["entity_type"] == "retailclaw_shrinkage"
        assert audits[0]["entity_id"] == sid
        assert json.loads(audits[0]["new_values"]) == {
            "cause": "damage", "quantity": "2.50"}
        # No ledger posting: shrinkage records quantity/value only.
        assert _count(conn, "gl_entry") == before_gl == 0
        assert _count(conn, "stock_ledger_entry") == before_sle == 0

    def test_second_record_leaves_first_untouched(self, conn, env):
        loc = _add_location(conn, env, "Downtown")
        first = call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item1"], quantity="1", cause="theft",
            discovered_date="2026-09-02", reported_by=None,
            value_lost="10.00", notes=None,
        ))["shrinkage_id"]
        before = dict(_one(conn, "retailclaw_shrinkage", "id", first))
        second = call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item2"], quantity="3", cause="spoilage",
            discovered_date="2026-09-03", reported_by=None,
            value_lost="5.00", notes=None,
        ))["shrinkage_id"]
        assert second != first
        assert dict(_one(conn, "retailclaw_shrinkage", "id", first)) == before
        assert _one(conn, "retailclaw_shrinkage", "id", second)["quantity"] == "3"

    def test_invalid_cause_refused_without_write(self, conn, env):
        before = _snapshot(conn)
        r = call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=None,
            item_id=env["item1"], quantity="1", cause="rust",
            discovered_date="2026-09-02", reported_by=None,
            value_lost="10.00", notes=None,
        ))
        assert is_error(r), r
        assert r["message"] == (
            "Invalid cause: rust. Must be one of: theft, damage, spoilage, "
            "admin_error, vendor_fraud, unknown")
        assert _snapshot(conn) == before


class TestListShrinkage:
    def test_list_returns_stored_rows_exactly(self, conn, env):
        loc = _add_location(conn, env, "Downtown")
        call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item1"], quantity="1", cause="theft",
            discovered_date="2026-09-02", reported_by=None,
            value_lost="10.00", notes=None,
        ))
        call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item2"], quantity="2.50", cause="damage",
            discovered_date="2026-09-01", reported_by=None,
            value_lost="19.99", notes=None,
        ))
        r = call_action(mod.retail_list_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=None,
            cause=None, limit=50, offset=0,
        ))
        assert is_ok(r), r
        assert r["total_count"] == 2
        got = {(row["cause"], row["quantity"], row["value_lost"])
               for row in r["shrinkage_records"]}
        assert got == {("theft", "1", "10.00"), ("damage", "2.50", "19.99")}
        db_rows = {(row["cause"], row["quantity"], row["value_lost"])
                   for row in _all(conn, "retailclaw_shrinkage")}
        assert got == db_rows
        # No ledger involvement: list is a pure read of retailclaw_shrinkage.
        assert _count(conn, "gl_entry") == 0

    def test_list_filters_by_cause(self, conn, env):
        loc = _add_location(conn, env, "Downtown")
        call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item1"], quantity="1", cause="theft",
            discovered_date="2026-09-02", reported_by=None,
            value_lost="10.00", notes=None,
        ))
        call_action(mod.retail_record_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=loc,
            item_id=env["item2"], quantity="2.50", cause="damage",
            discovered_date="2026-09-01", reported_by=None,
            value_lost="19.99", notes=None,
        ))
        r = call_action(mod.retail_list_shrinkage, conn, ns(
            company_id=env["company_id"], store_location_id=None,
            cause="theft", limit=50, offset=0,
        ))
        assert is_ok(r), r
        assert r["total_count"] == 1
        assert r["shrinkage_records"][0]["cause"] == "theft"
        assert r["shrinkage_records"][0]["quantity"] == "1"

    def test_unknown_company_refuses_without_write(self, conn, env):
        # An unknown company id refuses (never an empty page) and writes
        # nothing.
        before = _snapshot(conn)
        r = call_action(mod.retail_list_shrinkage, conn, ns(
            company_id="no-such-company", store_location_id=None,
            cause=None, limit=50, offset=0,
        ))
        assert r == {"status": "error",
                     "error": "Company not found: no-such-company",
                     "message": "Company not found: no-such-company"}, r
        assert _snapshot(conn) == before


class TestListStoreSchedules:
    def test_list_reflects_stored_locations(self, conn, env):
        downtown = _add_location(conn, env, "Downtown")
        depot = _add_location(conn, env, "Depot", store_type="warehouse")
        call_action(mod.retail_add_store_shift, conn, ns(
            company_id=env["company_id"], store_location_id=downtown,
            name="Morning", start_date=None, end_date=None,
        ))
        r = call_action(mod.retail_list_store_schedules, conn, ns(
            company_id=env["company_id"], store_location_id=None,
        ))
        assert is_ok(r), r
        assert r["store_count"] == 2
        by_name = {s["name"]: s for s in r["stores"]}
        assert by_name["Downtown"]["store_type"] == "retail"
        assert by_name["Depot"]["store_type"] == "warehouse"
        assert {s["status"] for s in r["stores"]} == {"active"}
        db_names = {row["name"] for row in _all(conn, "retailclaw_store_location")}
        assert set(by_name) == db_names == {"Downtown", "Depot"}
        assert downtown in {row["id"] for row in _all(conn, "retailclaw_store_location")}
        assert depot in {row["id"] for row in _all(conn, "retailclaw_store_location")}
        # A shift writes an audit row only, never a schedule row: the count is
        # unchanged by retail-add-store-shift. No ledger involvement either.
        assert _count(conn, "gl_entry") == 0

    def test_unknown_location_refused_without_write(self, conn, env):
        _add_location(conn, env, "Downtown")
        before = _snapshot(conn)
        r = call_action(mod.retail_list_store_schedules, conn, ns(
            company_id=env["company_id"], store_location_id="no-such-store",
        ))
        assert is_error(r), r
        assert r["message"] == "Store location no-such-store not found"
        assert _snapshot(conn) == before


class TestLoyaltyReport:
    def test_report_matches_stored_members_and_transactions(self, conn, env):
        prog = _add_program(conn, env)
        alice = _add_member(conn, env, prog, "Alice", tier="bronze")
        bob = _add_member(conn, env, prog, "Bob", tier="silver")
        assert is_ok(call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=alice, points=100, reference_type=None,
            reference_id=None, description=None)))
        assert is_ok(call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=bob, points=50, reference_type=None,
            reference_id=None, description=None)))
        assert is_ok(call_action(mod.retail_redeem_loyalty_points, conn, ns(
            member_id=alice, points=30, reference_type=None,
            reference_id=None, description=None)))
        assert _one(conn, "retailclaw_loyalty_member", "id", alice)["points_balance"] == 70
        assert _one(conn, "retailclaw_loyalty_member", "id", bob)["points_balance"] == 50
        r = call_action(mod.retail_loyalty_report, conn, ns(
            company_id=env["company_id"], program_id=None,
        ))
        assert is_ok(r), r
        assert r["total_members"] == 2
        assert r["total_points_balance"] == 120
        assert r["total_lifetime_points"] == 150
        tiers = {t["tier"]: t for t in r["tiers"]}
        assert tiers["bronze"]["member_count"] == 1
        assert tiers["bronze"]["total_points_balance"] == 70
        assert tiers["bronze"]["total_lifetime_points"] == 100
        assert tiers["silver"]["member_count"] == 1
        assert tiers["silver"]["total_points_balance"] == 50
        assert tiers["silver"]["total_lifetime_points"] == 50
        assert r["transactions"]["earn"] == {"count": 2, "total_points": 150}
        assert r["transactions"]["redeem"] == {"count": 1, "total_points": 30}
        # Points are counts, not money: asserted as ints, and the report never
        # touches the ledger.

    def test_unknown_company_refuses_without_write(self, conn, env):
        # An unknown company id refuses (never zeros) and writes nothing.
        before = _snapshot(conn)
        r = call_action(mod.retail_loyalty_report, conn, ns(
            company_id="no-such-company", program_id=None,
        ))
        assert r == {"status": "error",
                     "error": "Company not found: no-such-company",
                     "message": "Company not found: no-such-company"}, r
        assert _snapshot(conn) == before


class TestMarginAnalysis:
    def test_margins_match_stored_rates_exactly(self, conn, env):
        pl = _add_price_list(conn, env)
        _add_price_list_item(conn, pl, env["item1"], "Alpha", "30.00")
        _add_price_list_item(conn, pl, env["item2"], "Beta", "25.99")
        r = call_action(mod.retail_add_wholesale_price, conn, ns(
            company_id=env["company_id"], wholesale_customer_id=None,
            item_id=env["item1"], item_name="Alpha", wholesale_rate="12.50",
            min_order_qty=None, currency=None, valid_from=None,
            valid_to=None,
        ))
        assert is_ok(r), r
        assert _one(conn, "retailclaw_wholesale_price",
                    "item_id", env["item1"])["wholesale_rate"] == "12.50"
        r = call_action(mod.retail_margin_analysis, conn, ns(
            company_id=env["company_id"], limit=50, offset=0,
        ))
        assert is_ok(r), r
        assert r["total_items"] == 2
        rows = {row["item_name"]: row for row in r["rows"]}
        assert rows["Alpha"]["retail_rate"] == "30.00"
        assert rows["Alpha"]["wholesale_rate"] == "12.50"
        assert rows["Alpha"]["margin"] == "17.50"
        assert rows["Alpha"]["margin_pct"] == "58.33"
        assert Decimal(rows["Alpha"]["margin"]) == (
            Decimal(rows["Alpha"]["retail_rate"]) - Decimal("12.50"))
        assert rows["Beta"]["retail_rate"] == "25.99"
        assert rows["Beta"]["wholesale_rate"] == "0.00"
        assert rows["Beta"]["margin"] == "25.99"
        assert rows["Beta"]["margin_pct"] == "100.00"
        # Pure read across two stored tables; never touches the ledger.

    def test_unknown_company_refuses_without_write(self, conn, env):
        # An unknown company id refuses (never zero rows) and writes nothing.
        before = _snapshot(conn)
        r = call_action(mod.retail_margin_analysis, conn, ns(
            company_id="no-such-company", limit=50, offset=0,
        ))
        assert r == {"status": "error",
                     "error": "Company not found: no-such-company",
                     "message": "Company not found: no-such-company"}, r
        assert _snapshot(conn) == before


class TestOmnichannelSalesReport:
    def test_report_matches_stored_channels_and_catalog(self, conn, env):
        _add_location(conn, env, "Physical Store", store_type="retail")
        _add_location(conn, env, "Web Shop", store_type="online")
        pl = _add_price_list(conn, env)
        _add_price_list_item(conn, pl, env["item1"], "Alpha", "20.00")
        _add_price_list_item(conn, pl, env["item2"], "Beta", "15.00")
        wc = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"], customer_id=None,
            business_name="Acme", contact_name=None, email=None, phone=None,
            tax_id=None, credit_limit=None, payment_terms=None,
            discount_pct=None, address_line1=None, address_line2=None,
            city=None, state=None, zip_code=None,
        ))
        assert is_ok(wc), wc
        wo = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"], wholesale_customer_id=wc["id"],
            order_date="2026-09-01", expected_delivery_date=None, notes=None,
        ))
        assert is_ok(wo), wo
        assert is_ok(call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=wo["id"], item_id=None, item_name="Alpha",
            rate="20.00", qty=2, notes=None,
        )))
        assert _one(conn, "retailclaw_wholesale_order",
                    "id", wo["id"])["order_status"] == "draft"
        assert _one(conn, "retailclaw_wholesale_order",
                    "id", wo["id"])["total"] == "40.00"
        r = call_action(mod.retail_omnichannel_sales_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r), r
        assert r["total_channels"] == 2
        channels = {c["channel_type"]: c for c in r["channels"]}
        assert set(channels) == {"retail", "online"}
        for channel in channels.values():
            assert channel["location_count"] == 1
            assert channel["catalog_items"] == 2
            assert channel["catalog_value"] == "35.00"
            assert Decimal(channel["catalog_value"]) == Decimal("35.00")
        # Draft wholesale orders are excluded from wholesale totals even though
        # a draft order with total 40.00 is stored. Documented, not fixed.
        assert r["wholesale_orders"] == 0
        assert r["wholesale_sales"] == "0.00"
        assert _count(conn, "retailclaw_store_location") == 2
        # Pure read; never touches the ledger.

    def test_missing_company_refused_without_write(self, conn, env):
        before = _snapshot(conn)
        r = call_action(mod.retail_omnichannel_sales_report, conn, ns(
            company_id=None,
        ))
        assert is_error(r), r
        assert r["message"] == "--company-id is required"
        assert _snapshot(conn) == before


class TestPromotionEffectiveness:
    def test_report_matches_stored_promotions(self, conn, env):
        summer = _add_promotion(conn, env, "Summer Sale", "percentage",
                                "15.00", max_uses=10)
        winter = _add_promotion(conn, env, "Winter Draft", "fixed", "5.00")
        assert is_ok(call_action(mod.retail_activate_promotion, conn, ns(
            promotion_id=summer,
        )))
        assert _one(conn, "retailclaw_promotion",
                    "id", summer)["promo_status"] == "active"
        assert _one(conn, "retailclaw_promotion",
                    "id", summer)["discount_value"] == "15.00"
        r = call_action(mod.retail_promotion_effectiveness, conn, ns(
            company_id=env["company_id"], promo_status=None,
            limit=50, offset=0,
        ))
        assert is_ok(r), r
        assert r["total_promotions"] == 2
        rows = {row["name"]: row for row in r["rows"]}
        assert rows["Summer Sale"]["used_count"] == 0
        assert rows["Summer Sale"]["max_uses"] == 10
        assert rows["Summer Sale"]["utilization_pct"] == 0.0
        assert rows["Summer Sale"]["promo_status"] == "active"
        assert rows["Summer Sale"]["discount_value"] == "15.00"
        assert rows["Winter Draft"]["used_count"] == 0
        assert rows["Winter Draft"]["max_uses"] is None
        assert rows["Winter Draft"]["utilization_pct"] is None
        assert rows["Winter Draft"]["promo_status"] == "draft"
        active = call_action(mod.retail_promotion_effectiveness, conn, ns(
            company_id=env["company_id"], promo_status="active",
            limit=50, offset=0,
        ))
        assert is_ok(active), active
        assert active["total_promotions"] == 1
        assert active["rows"][0]["name"] == "Summer Sale"
        # Pure read of stored promotion rows; never touches the ledger.

    def test_unknown_company_refuses_without_write(self, conn, env):
        # An unknown company id refuses (never zero rows) and writes nothing.
        before = _snapshot(conn)
        r = call_action(mod.retail_promotion_effectiveness, conn, ns(
            company_id="no-such-company", promo_status=None,
            limit=50, offset=0,
        ))
        assert r == {"status": "error",
                     "error": "Company not found: no-such-company",
                     "message": "Company not found: no-such-company"}, r
        assert _snapshot(conn) == before


class TestRedeemStoreCredit:
    def test_partial_then_full_redemption_updates_row_exactly(self, conn, env):
        other = seed_customer(conn, env["company_id"], "Other Customer")
        issue = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount="100.00", source="return", reference_id=None,
            expiration_date=None,
        ))
        assert is_ok(issue), issue
        sc_id = issue["store_credit_id"]
        other_issue = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=other,
            amount="50.00", source="gift", reference_id=None,
            expiration_date=None,
        ))
        other_id = other_issue["store_credit_id"]
        r = call_action(mod.retail_redeem_store_credit, conn, ns(
            store_credit_id=sc_id, amount="30.00",
        ))
        assert is_ok(r), r
        assert r["redeemed_amount"] == "30.00"
        assert r["remaining_balance"] == "70.00"
        row = _one(conn, "retailclaw_store_credit", "id", sc_id)
        assert row["original_amount"] == "100.00"
        assert row["remaining_balance"] == "70.00"
        assert Decimal(row["remaining_balance"]) == Decimal("70.00")
        assert row["status"] == "active"
        assert _one(conn, "retailclaw_store_credit",
                    "id", other_id)["remaining_balance"] == "50.00"
        r = call_action(mod.retail_redeem_store_credit, conn, ns(
            store_credit_id=sc_id, amount="70.00",
        ))
        assert is_ok(r), r
        row = _one(conn, "retailclaw_store_credit", "id", sc_id)
        assert (row["remaining_balance"], row["status"]) == ("0.00", "redeemed")
        assert row["original_amount"] == "100.00"
        redeems = [dict(a) for a in _all(conn, "audit_log")
                   if a["action"] == "retail-redeem-store-credit"]
        assert len(redeems) == 2
        assert json.loads(redeems[0]["new_values"]) == {
            "redeemed": "30.00", "remaining": "70.00"}
        # Store credit moves value between stored balances only; it never
        # posts to the ledger.
        assert _count(conn, "gl_entry") == 0

    def test_over_redemption_refused_without_write(self, conn, env):
        sc_id = call_action(mod.retail_issue_store_credit, conn, ns(
            company_id=env["company_id"], customer_id=env["customer_id"],
            amount="50.00", source="return", reference_id=None,
            expiration_date=None,
        ))["store_credit_id"]
        before = _snapshot(conn)
        r = call_action(mod.retail_redeem_store_credit, conn, ns(
            store_credit_id=sc_id, amount="50.01",
        ))
        assert is_error(r), r
        assert r["message"] == (
            "Redemption amount 50.01 exceeds remaining balance 50.00")
        assert _snapshot(conn) == before


class TestRequestInterStoreTransfer:
    def test_request_writes_audit_only_no_stock_movement(self, conn, env):
        src = _add_location(conn, env, "Store A")
        dst = _add_location(conn, env, "Store B")
        before = _snapshot(conn)
        r = call_action(mod.retail_request_inter_store_transfer, conn, ns(
            from_location_id=src, to_location_id=dst,
            item_id=env["item1"], qty="3",
        ))
        assert is_ok(r), r
        assert r["transfer_status"] == "draft"
        assert r["qty"] == 3
        transfer_id = r["transfer_id"]
        # No stock_entry, stock_ledger_entry or gl_entry row is persisted: the
        # cross-skill stock entry is best-effort and the transfer itself lives
        # only in the response plus one audit row. Documented, not fixed.
        assert _count(conn, "stock_entry") == 0
        assert _count(conn, "stock_ledger_entry") == 0
        assert _count(conn, "gl_entry") == 0
        audits = [dict(a) for a in _all(conn, "audit_log")
                  if a["action"] == "retail-request-inter-store-transfer"]
        assert len(audits) == 1
        assert audits[0]["skill"] == "retailclaw"
        assert audits[0]["entity_type"] == "retailclaw_store_location"
        assert audits[0]["entity_id"] == transfer_id
        assert json.loads(audits[0]["new_values"]) == {
            "from": src, "to": dst, "item_id": env["item1"], "qty": 3}
        assert audits[0]["old_values"] is None
        assert _one(conn, "retailclaw_store_location",
                    "id", src)["name"] == "Store A"
        assert _one(conn, "retailclaw_store_location",
                    "id", dst)["name"] == "Store B"
        after = _snapshot(conn)
        assert after["stock_entry"] == before["stock_entry"] == []
        assert after["gl_entry"] == before["gl_entry"] == []

    def test_same_location_refused_without_write(self, conn, env):
        src = _add_location(conn, env, "Store A")
        before = _snapshot(conn)
        r = call_action(mod.retail_request_inter_store_transfer, conn, ns(
            from_location_id=src, to_location_id=src,
            item_id=env["item1"], qty="3",
        ))
        assert is_error(r), r
        assert r["message"] == "Source and destination locations must be different"
        assert _snapshot(conn) == before


class TestListInterStoreTransfers:
    def test_list_stays_empty_despite_transfer_rows(self, conn, env):
        # DEFECT documented, not fixed: the list query reads
        # se.entry_type / se.total_qty, but stock_entry carries
        # stock_entry_type and no total_qty column, so the query always raises
        # and the handler swallows it into an empty result.
        src = _add_location(conn, env, "Store A")
        dst = _add_location(conn, env, "Store B")
        r = call_action(mod.retail_request_inter_store_transfer, conn, ns(
            from_location_id=src, to_location_id=dst,
            item_id=env["item1"], qty="3",
        ))
        assert is_ok(r), r
        _seed_stock_entry(conn, env)
        assert _count(conn, "stock_entry") == 1
        r = call_action(mod.retail_list_inter_store_transfers, conn, ns(
            company_id=env["company_id"], status=None, limit=50, offset=0,
        ))
        assert is_ok(r), r
        assert r["transfers"] == []
        assert r["count"] == 0
        assert r["message"] == "stock_entry table not available"
        assert _count(conn, "stock_entry") == 1
        # Never touches the ledger; it does not even reach its own table.

    def test_missing_company_refused_without_write(self, conn, env):
        before = _snapshot(conn)
        r = call_action(mod.retail_list_inter_store_transfers, conn, ns(
            company_id=None, status=None, limit=50, offset=0,
        ))
        assert is_error(r), r
        assert r["message"] == "--company-id is required"
        assert _snapshot(conn) == before


class TestListCustomerSegments:
    def test_report_counts_seeded_segments_exactly(self, conn, env):
        # Fixed m655: submitted statuses aggregate with DecimalSum; draft and
        # cancelled invoices do not count.
        from datetime import date as _date

        today = _date.today().isoformat()
        _seed_sales_invoice(conn, env, env["customer_id"], today, "6000.00",
                            status="submitted")
        _seed_sales_invoice(conn, env, env["customer_id"], today, "500.00",
                            status="paid")
        _seed_sales_invoice(conn, env, env["customer_id"], today, "99.00",
                            status="draft")
        _seed_sales_invoice(conn, env, env["customer_id"], today, "77.00",
                            status="cancelled")
        before = _snapshot(conn)
        r = call_action(mod.retail_list_customer_segments, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r), r
        assert r["company_id"] == env["company_id"]
        assert r["total_customers"] == 1
        assert r["segments"] == {
            "champion": 0, "loyal": 1, "potential": 0,
            "at_risk": 0, "dormant": 0,
        }
        assert _snapshot(conn) == before

    def test_missing_company_refused_without_write(self, conn, env):
        before = _snapshot(conn)
        r = call_action(mod.retail_list_customer_segments, conn, ns(
            company_id=None,
        ))
        assert is_error(r), r
        assert r["message"] == "--company-id is required"
        assert _snapshot(conn) == before


class TestProcurementReport:
    def test_report_counts_shared_catalog_with_exact_pct(self, conn, env):
        # Fixed m655: the catalog is shared (no item.company_id); company
        # stock is the exact Decimal sum over the company's warehouses.
        # Env holds two stock items; item1 at reorder level 10 with no stock
        # rows (counts as zero, below reorder), item2 with no reorder level.
        sql, params = dynamic_update("item", {"reorder_level": "10"},
                                     where={"id": env["item1"]})
        conn.execute(sql, params)
        conn.commit()
        assert _one(conn, "item", "id", env["item1"])["reorder_level"] == "10"
        assert _one(conn, "item", "id", env["item2"])["reorder_level"] is None
        before = _snapshot(conn)
        r = call_action(mod.retail_procurement_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(r), r
        assert r["company_id"] == env["company_id"]
        assert r["total_stock_items"] == 2
        assert r["items_below_reorder"] == 1
        assert r["reorder_pct"] == "50.0"
        assert Decimal(r["reorder_pct"]) == Decimal("50.0")
        assert _snapshot(conn) == before

    def test_missing_company_refused_without_write(self, conn, env):
        before = _snapshot(conn)
        r = call_action(mod.retail_procurement_report, conn, ns(
            company_id=None,
        ))
        assert is_error(r), r
        assert r["message"] == "--company-id is required"
        assert _snapshot(conn) == before
