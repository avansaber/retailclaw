"""Audit rows name the table and the record they changed (m702).

Every audit row stores skill=retailclaw, action=<action name>,
entity_type=<table>, entity_id=<record id> so a record's history is found
by its id.
"""
import json
import uuid

from retail_helpers import call_action, ns, is_ok, load_db_query

mod = load_db_query()

try:
    import importlib.util
    import os
    import sys
    _SETUP_LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "..", "..", "erpclaw", "scripts",
                              "erpclaw-setup", "lib")
    _SETUP_LIB = os.path.normpath(_SETUP_LIB)
    if os.path.isdir(os.path.join(_SETUP_LIB, "erpclaw_lib")):
        if _SETUP_LIB not in sys.path and importlib.util.find_spec("erpclaw_lib") is None:
            sys.path.insert(0, _SETUP_LIB)
    from erpclaw_lib.query import Q, Table, Field, P
except ImportError:
    pass


def _rows_for(conn, entity_id):
    t = Table("audit_log")
    q = Q.from_(t).select(t.skill, t.action, t.entity_type, t.entity_id,
                          t.new_values).where(t.entity_id == P())
    return conn.execute(q.get_sql(), (entity_id,)).fetchall()


def _assert_one(conn, record_id, skill, action, entity_type):
    rows = _rows_for(conn, record_id)
    matching = [r for r in rows
                if (r["skill"], r["action"], r["entity_type"]) == (skill, action, entity_type)]
    assert len(matching) == 1, (
        f"expected exactly one audit row for entity_id={record_id} "
        f"with {(skill, action, entity_type)}, got {len(matching)} "
        f"of {len(rows)} rows: "
        + str([(r['skill'], r['action'], r['entity_type'], r['entity_id']) for r in rows]))
    return matching[0]


def _add_location(conn, env, name="Audit Store"):
    r = call_action(mod.retail_add_store_location, conn, ns(
        company_id=env["company_id"], name=name, store_code=None,
        warehouse_id=None, address_line1="1 Main St", city="Austin",
        state="TX", zip_code="78701", store_type="retail",
        manager_name=None, phone=None))
    assert is_ok(r), r
    return r["id"]


def test_ecommerce_audit_rows(conn, env):
    order_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO sales_order (id, customer_id, order_date, status, company_id)"
        " VALUES (?, ?, '2026-03-01', 'draft', ?)",
        (order_id, env["customer_id"], env["company_id"]))
    conn.commit()
    r = call_action(mod.retail_fulfill_online_order, conn, ns(
        company_id=env["company_id"], order_id=order_id,
        tracking_number="TRK-1", carrier="UPS"))
    assert is_ok(r), r
    assert r["order_id"] == order_id
    _assert_one(conn, order_id, "retailclaw", "retail-fulfill-online-order", "sales_order")


def test_locations_audit_rows(conn, env):
    loc_id = _add_location(conn, env, "Audit Store A")
    _assert_one(conn, loc_id, "retailclaw", "retail-add-store-location",
                "retailclaw_store_location")
    u = call_action(mod.retail_update_store_location, conn, ns(
        store_location_id=loc_id, name="Audit Store A2", store_code=None,
        warehouse_id=None, address_line1=None, city=None, state=None,
        zip_code=None, store_type=None, manager_name=None, phone=None,
        location_status=None))
    assert is_ok(u), u
    _assert_one(conn, loc_id, "retailclaw", "retail-update-store-location",
                "retailclaw_store_location")
    src = _add_location(conn, env, "Audit Src")
    dst = _add_location(conn, env, "Audit Dst")
    t = call_action(mod.retail_request_inter_store_transfer, conn, ns(
        from_location_id=src, to_location_id=dst,
        item_id=env["item1"], qty="3"))
    assert is_ok(t), t
    _assert_one(conn, t["transfer_id"], "retailclaw",
                "retail-request-inter-store-transfer", "retailclaw_store_location")


def test_loyalty_audit_rows(conn, env):
    prog = call_action(mod.retail_add_loyalty_program, conn, ns(
        company_id=env["company_id"], name="Audit Program", description=None,
        points_per_dollar="1", redemption_rate="0.01", tiers=None))
    assert is_ok(prog), prog
    prog_id = prog["id"]
    _assert_one(conn, prog_id, "retailclaw", "retail-add-loyalty-program",
                "retailclaw_loyalty_program")
    mem = call_action(mod.retail_add_loyalty_member, conn, ns(
        company_id=env["company_id"], program_id=prog_id,
        customer_id=env["customer_id"], customer_name="Audit Member",
        email="audit@test.com", phone=None, member_tier=None,
        enrollment_date="2026-01-01"))
    assert is_ok(mem), mem
    mem_id = mem["id"]
    _assert_one(conn, mem_id, "retailclaw", "retail-add-loyalty-member",
                "retailclaw_loyalty_member")
    um = call_action(mod.retail_update_loyalty_member, conn, ns(
        member_id=mem_id, customer_name=None, email=None, phone=None,
        member_tier="gold", member_status=None))
    assert is_ok(um), um
    _assert_one(conn, mem_id, "retailclaw", "retail-update-loyalty-member",
                "retailclaw_loyalty_member")
    ap = call_action(mod.retail_add_loyalty_points, conn, ns(
        member_id=mem_id, points=500, reference_type="sale",
        reference_id="INV-001", description="Audit points"))
    assert is_ok(ap), ap
    _assert_one(conn, mem_id, "retailclaw", "retail-add-loyalty-points",
                "retailclaw_loyalty_member")
    rp = call_action(mod.retail_redeem_loyalty_points, conn, ns(
        member_id=mem_id, points=200, reference_type="redemption",
        reference_id="RDM-001", description="Audit redeem"))
    assert is_ok(rp), rp
    _assert_one(conn, mem_id, "retailclaw", "retail-redeem-loyalty-points",
                "retailclaw_loyalty_member")
    gc = call_action(mod.retail_add_gift_card, conn, ns(
        company_id=env["company_id"], card_number="GC-AUDIT-001",
        initial_balance="100.00", currency="USD", purchaser_name=None,
        recipient_name=None, recipient_email=None, issue_date="2026-03-01",
        expiration_date=None))
    assert is_ok(gc), gc
    gc_id = gc["id"]
    _assert_one(conn, gc_id, "retailclaw", "retail-add-gift-card",
                "retailclaw_gift_card")
    rd = call_action(mod.retail_redeem_gift_card, conn, ns(
        card_number="GC-AUDIT-001", gift_card_id=None, amount="30.00"))
    assert is_ok(rd), rd
    _assert_one(conn, gc_id, "retailclaw", "retail-redeem-gift-card",
                "retailclaw_gift_card")


def test_merchandising_audit_rows(conn, env):
    cat = call_action(mod.retail_add_category, conn, ns(
        company_id=env["company_id"], name="Audit Cat", parent_id=None,
        description=None, sort_order="1", is_active=None))
    assert is_ok(cat), cat
    cat_id = cat["id"]
    _assert_one(conn, cat_id, "retailclaw", "retail-add-category",
                "retailclaw_category")
    uc = call_action(mod.retail_update_category, conn, ns(
        category_id=cat_id, name="Audit Cat 2", description=None,
        sort_order=None, is_active=None, parent_id=None))
    assert is_ok(uc), uc
    _assert_one(conn, cat_id, "retailclaw", "retail-update-category",
                "retailclaw_category")
    plano = call_action(mod.retail_add_planogram, conn, ns(
        company_id=env["company_id"], name="Audit Plano", description=None,
        store_section="Aisle 1", fixture_type="shelf", shelf_count="4",
        width_inches=None, height_inches=None, effective_date=None))
    assert is_ok(plano), plano
    plano_id = plano["id"]
    _assert_one(conn, plano_id, "retailclaw", "retail-add-planogram",
                "retailclaw_planogram")
    up = call_action(mod.retail_update_planogram, conn, ns(
        planogram_id=plano_id, name=None, description=None,
        store_section="Front", fixture_type=None, effective_date=None,
        width_inches=None, height_inches=None, shelf_count=None,
        planogram_status=None))
    assert is_ok(up), up
    _assert_one(conn, plano_id, "retailclaw", "retail-update-planogram",
                "retailclaw_planogram")
    pi = call_action(mod.retail_add_planogram_item, conn, ns(
        planogram_id=plano_id, item_id=env["item1"], item_name="Widget A",
        shelf_number="1", position="1", facings="2", min_stock=None,
        max_stock=None, notes=None))
    assert is_ok(pi), pi
    _assert_one(conn, pi["id"], "retailclaw", "retail-add-planogram-item",
                "retailclaw_planogram_item")


def test_pricing_audit_rows(conn, env):
    pl = call_action(mod.retail_add_price_list, conn, ns(
        company_id=env["company_id"], name="Audit PL", description=None,
        price_list_type="selling", currency="USD", is_default=None,
        valid_from=None, valid_to=None))
    assert is_ok(pl), pl
    pl_id = pl["id"]
    _assert_one(conn, pl_id, "retailclaw", "retail-add-price-list",
                "retailclaw_price_list")
    upl = call_action(mod.retail_update_price_list, conn, ns(
        price_list_id=pl_id, name="Audit PL 2", description=None,
        currency=None, valid_from=None, valid_to=None, price_list_type=None,
        price_list_status=None))
    assert is_ok(upl), upl
    _assert_one(conn, pl_id, "retailclaw", "retail-update-price-list",
                "retailclaw_price_list")
    pli = call_action(mod.retail_add_price_list_item, conn, ns(
        price_list_id=pl_id, item_id=env["item1"], item_name="Widget A",
        rate="29.99", min_qty="1", currency="USD", valid_from=None,
        valid_to=None))
    assert is_ok(pli), pli
    pli_id = pli["id"]
    _assert_one(conn, pli_id, "retailclaw", "retail-add-price-list-item",
                "retailclaw_price_list_item")
    upli = call_action(mod.retail_update_price_list_item, conn, ns(
        price_list_item_id=pli_id, item_name=None, currency=None,
        valid_from=None, valid_to=None, rate="39.99", min_qty=None))
    assert is_ok(upli), upli
    _assert_one(conn, pli_id, "retailclaw", "retail-update-price-list-item",
                "retailclaw_price_list_item")
    promo = call_action(mod.retail_add_promotion, conn, ns(
        company_id=env["company_id"], name="Audit Promo", description=None,
        promo_type="percentage", discount_value="10", min_purchase=None,
        max_discount=None, max_uses=None, applicable_items=None,
        applicable_categories=None, start_date="2026-01-01",
        end_date="2026-12-31"))
    assert is_ok(promo), promo
    promo_id = promo["id"]
    _assert_one(conn, promo_id, "retailclaw", "retail-add-promotion",
                "retailclaw_promotion")
    upr = call_action(mod.retail_update_promotion, conn, ns(
        promotion_id=promo_id, name="Audit Promo 2", description=None,
        start_date=None, end_date=None, applicable_items=None,
        applicable_categories=None, promo_type=None, discount_value="15",
        min_purchase=None, max_uses=None))
    assert is_ok(upr), upr
    _assert_one(conn, promo_id, "retailclaw", "retail-update-promotion",
                "retailclaw_promotion")
    act = call_action(mod.retail_activate_promotion, conn, ns(
        promotion_id=promo_id))
    assert is_ok(act), act
    _assert_one(conn, promo_id, "retailclaw", "retail-activate-promotion",
                "retailclaw_promotion")
    deact = call_action(mod.retail_deactivate_promotion, conn, ns(
        promotion_id=promo_id))
    assert is_ok(deact), deact
    _assert_one(conn, promo_id, "retailclaw", "retail-deactivate-promotion",
                "retailclaw_promotion")


def test_returns_audit_rows(conn, env):
    ra = call_action(mod.retail_add_return_authorization, conn, ns(
        company_id=env["company_id"], customer_id=env["customer_id"],
        customer_name="Audit Return", return_date="2026-03-10",
        reason="Audit reason", return_type="refund", original_invoice_id=None,
        notes=None))
    assert is_ok(ra), ra
    ra_id = ra["id"]
    _assert_one(conn, ra_id, "retailclaw", "retail-add-return-authorization",
                "retailclaw_return_authorization")
    ur = call_action(mod.retail_update_return_authorization, conn, ns(
        return_id=ra_id, customer_name=None, reason="Updated audit reason",
        original_invoice_id=None, notes=None, return_type=None,
        return_status="approved", restocking_fee=None))
    assert is_ok(ur), ur
    _assert_one(conn, ra_id, "retailclaw", "retail-update-return-authorization",
                "retailclaw_return_authorization")
    ri = call_action(mod.retail_add_return_item, conn, ns(
        return_id=ra_id, item_id=env["item1"], item_name="Widget A", qty="2",
        rate="30.00", reason=None, item_condition="good",
        disposition="restock"))
    assert is_ok(ri), ri
    _assert_one(conn, ri["id"], "retailclaw", "retail-add-return-item",
                "retailclaw_return_item")
    pr = call_action(mod.retail_process_return, conn, ns(
        return_id=ra_id, return_status="completed",
        sales_returns_account_id=env["sales_returns_acct"],
        cash_account_id=env["cash_acct"], inventory_account_id=None,
        cogs_account_id=None, cost_center_id=env["cc"], restock_cost=None))
    assert is_ok(pr), pr
    _assert_one(conn, ra_id, "retailclaw", "retail-process-return",
                "retailclaw_return_authorization")
    ra2 = call_action(mod.retail_add_return_authorization, conn, ns(
        company_id=env["company_id"], customer_id=None,
        customer_name="Audit Exchange Return", return_date="2026-03-11",
        reason="Wrong size", return_type="exchange", original_invoice_id=None,
        notes=None))
    assert is_ok(ra2), ra2
    ex = call_action(mod.retail_add_exchange, conn, ns(
        company_id=env["company_id"], return_id=ra2["id"],
        original_item_id=env["item1"], original_item_name="Widget A",
        new_item_id=env["item2"], new_item_name="Widget B", qty="1",
        price_difference="5.00", notes=None))
    assert is_ok(ex), ex
    _assert_one(conn, ex["id"], "retailclaw", "retail-add-exchange",
                "retailclaw_exchange")


def test_wholesale_audit_rows(conn, env):
    wc = call_action(mod.retail_add_wholesale_customer, conn, ns(
        company_id=env["company_id"], customer_id=None,
        business_name="Audit Wholesale", contact_name=None, email=None,
        phone=None, tax_id=None, credit_limit=None, payment_terms=None,
        discount_pct=None, address_line1=None, address_line2=None, city=None,
        state=None, zip_code=None))
    assert is_ok(wc), wc
    wc_id = wc["id"]
    _assert_one(conn, wc_id, "retailclaw", "retail-add-wholesale-customer",
                "retailclaw_wholesale_customer")
    uwc = call_action(mod.retail_update_wholesale_customer, conn, ns(
        wholesale_customer_id=wc_id, business_name=None, contact_name=None,
        email=None, phone=None, tax_id=None, credit_limit="75000",
        payment_terms=None, discount_pct=None, address_line1=None,
        address_line2=None, city=None, state=None, zip_code=None,
        wholesale_status=None))
    assert is_ok(uwc), uwc
    _assert_one(conn, wc_id, "retailclaw", "retail-update-wholesale-customer",
                "retailclaw_wholesale_customer")
    wp = call_action(mod.retail_add_wholesale_price, conn, ns(
        company_id=env["company_id"], wholesale_customer_id=wc_id,
        item_id=env["item1"], item_name="Widget A", wholesale_rate="15.50",
        min_order_qty="10", currency="USD", valid_from=None, valid_to=None))
    assert is_ok(wp), wp
    _assert_one(conn, wp["id"], "retailclaw", "retail-add-wholesale-price",
                "retailclaw_wholesale_price")
    wo = call_action(mod.retail_add_wholesale_order, conn, ns(
        company_id=env["company_id"], wholesale_customer_id=wc_id,
        order_date="2026-03-15", expected_delivery_date=None, notes=None))
    assert is_ok(wo), wo
    wo_id = wo["id"]
    _assert_one(conn, wo_id, "retailclaw", "retail-add-wholesale-order",
                "retailclaw_wholesale_order")
    oi = call_action(mod.retail_add_wholesale_order_item, conn, ns(
        wholesale_order_id=wo_id, item_id=env["item1"], item_name="Widget A",
        qty="10", rate="25.00", notes=None))
    assert is_ok(oi), oi
    _assert_one(conn, oi["id"], "retailclaw", "retail-add-wholesale-order-item",
                "retailclaw_wholesale_order_item")


def test_no_audit_row_is_keyed_by_company(conn, env):
    loc_id = _add_location(conn, env, "Key Check Store")
    pl = call_action(mod.retail_add_price_list, conn, ns(
        company_id=env["company_id"], name="Key Check PL", description=None,
        price_list_type="selling", currency="USD", is_default=None,
        valid_from=None, valid_to=None))
    assert is_ok(pl), pl
    ra = call_action(mod.retail_add_return_authorization, conn, ns(
        company_id=env["company_id"], customer_id=None,
        customer_name="Key Check", return_date="2026-03-10", reason=None,
        return_type="refund", original_invoice_id=None, notes=None))
    assert is_ok(ra), ra
    prog = call_action(mod.retail_add_loyalty_program, conn, ns(
        company_id=env["company_id"], name="Key Check Program",
        description=None, points_per_dollar=None, redemption_rate=None,
        tiers=None))
    assert is_ok(prog), prog
    cat = call_action(mod.retail_add_category, conn, ns(
        company_id=env["company_id"], name="Key Check Cat", parent_id=None,
        description=None, sort_order=None, is_active=None))
    assert is_ok(cat), cat
    wc = call_action(mod.retail_add_wholesale_customer, conn, ns(
        company_id=env["company_id"], customer_id=None,
        business_name="Key Check WC", contact_name=None, email=None,
        phone=None, tax_id=None, credit_limit=None, payment_terms=None,
        discount_pct=None, address_line1=None, address_line2=None, city=None,
        state=None, zip_code=None))
    assert is_ok(wc), wc
    t = Table("audit_log")
    q = Q.from_(t).select(t.skill, t.action, t.entity_type, t.entity_id)
    rows = conn.execute(q.get_sql(), ()).fetchall()
    assert len(rows) >= 3
    for r in rows:
        assert not r["skill"].startswith("retailclaw_"), r["skill"]
    keyed = [r for r in rows if r["skill"] == "retailclaw"
             and r["entity_id"] == env["company_id"]]
    assert keyed == []
    for r in rows:
        if r["skill"] == "retailclaw":
            assert r["action"].startswith("retail-"), r["action"]


def test_update_action_new_values(conn, env):
    loc_id = _add_location(conn, env, "NV Store")
    u = call_action(mod.retail_update_store_location, conn, ns(
        store_location_id=loc_id, name="NV Store 2", store_code=None,
        warehouse_id=None, address_line1=None, city=None, state=None,
        zip_code=None, store_type=None, manager_name=None, phone=None,
        location_status=None))
    assert is_ok(u), u
    changed = u["updated_fields"]
    row = _assert_one(conn, loc_id, "retailclaw",
                      "retail-update-store-location",
                      "retailclaw_store_location")
    assert json.loads(row["new_values"]) == {"updated_fields": changed}
