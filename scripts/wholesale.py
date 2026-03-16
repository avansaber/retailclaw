"""RetailClaw -- wholesale/B2B domain module

Actions for wholesale customers, pricing, and orders (4 tables, 10 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, LiteralValue, insert_row, update_row, dynamic_update

    ENTITY_PREFIXES.setdefault("retailclaw_wholesale_customer", "WSCUST-")
    ENTITY_PREFIXES.setdefault("retailclaw_wholesale_order", "WSO-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_WHOLESALE_STATUSES = ("active", "inactive", "suspended", "pending_approval")
VALID_ORDER_STATUSES = ("draft", "confirmed", "processing", "shipped", "delivered", "cancelled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone():
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _get_wholesale_customer(conn, wc_id):
    if not wc_id:
        err("--wholesale-customer-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_wholesale_customer")).select(Table("retailclaw_wholesale_customer").star).where(Field("id") == P()).get_sql(), (wc_id,)).fetchone()
    if not row:
        err(f"Wholesale customer {wc_id} not found")
    return row


# ===========================================================================
# 1. add-wholesale-customer
# ===========================================================================
def add_wholesale_customer(conn, args):
    _validate_company(conn, args.company_id)

    business_name = getattr(args, "business_name", None)
    if not business_name:
        err("--business-name is required")

    customer_id = getattr(args, "customer_id", None)
    if customer_id:
        if not conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (customer_id,)).fetchone():
            err(f"Customer {customer_id} not found")

    wc_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_wholesale_customer", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_wholesale_customer", {"id": P(), "naming_series": P(), "customer_id": P(), "business_name": P(), "contact_name": P(), "email": P(), "phone": P(), "tax_id": P(), "credit_limit": P(), "payment_terms": P(), "discount_pct": P(), "address_line1": P(), "address_line2": P(), "city": P(), "state": P(), "zip_code": P(), "wholesale_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        wc_id, naming, customer_id, business_name,
        getattr(args, "contact_name", None),
        getattr(args, "email", None),
        getattr(args, "phone", None),
        getattr(args, "tax_id", None),
        str(round_currency(to_decimal(getattr(args, "credit_limit", None) or "0"))),
        getattr(args, "payment_terms", None) or "Net 30",
        str(to_decimal(getattr(args, "discount_pct", None) or "0")),
        getattr(args, "address_line1", None),
        getattr(args, "address_line2", None),
        getattr(args, "city", None),
        getattr(args, "state", None),
        getattr(args, "zip_code", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_wholesale_customer", wc_id, "retail-add-wholesale-customer", args.company_id)
    conn.commit()
    ok({"id": wc_id, "naming_series": naming, "business_name": business_name, "wholesale_status": "active"})


# ===========================================================================
# 2. update-wholesale-customer
# ===========================================================================
def update_wholesale_customer(conn, args):
    wc_id = getattr(args, "wholesale_customer_id", None)
    _get_wholesale_customer(conn, wc_id)

    data, changed = {}, []
    for arg_name, col_name in {
        "business_name": "business_name", "contact_name": "contact_name",
        "email": "email", "phone": "phone", "tax_id": "tax_id",
        "payment_terms": "payment_terms",
        "address_line1": "address_line1", "address_line2": "address_line2",
        "city": "city", "state": "state", "zip_code": "zip_code",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    credit_limit = getattr(args, "credit_limit", None)
    if credit_limit is not None:
        data["credit_limit"] = str(round_currency(to_decimal(credit_limit)))
        changed.append("credit_limit")

    discount_pct = getattr(args, "discount_pct", None)
    if discount_pct is not None:
        data["discount_pct"] = str(to_decimal(discount_pct))
        changed.append("discount_pct")

    wholesale_status = getattr(args, "wholesale_status", None)
    if wholesale_status is not None:
        _validate_enum(wholesale_status, VALID_WHOLESALE_STATUSES, "wholesale-status")
        data["wholesale_status"] = wholesale_status
        changed.append("wholesale_status")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_wholesale_customer", data, where={"id": wc_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_wholesale_customer", wc_id, "retail-update-wholesale-customer", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": wc_id, "updated_fields": changed})


# ===========================================================================
# 3. list-wholesale-customers
# ===========================================================================
def list_wholesale_customers(conn, args):
    t = Table("retailclaw_wholesale_customer")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "wholesale_status", None):
        q = q.where(t.wholesale_status == P())
        qc = qc.where(t.wholesale_status == P())
        params.append(args.wholesale_status)
    if getattr(args, "search", None):
        q = q.where((t.business_name.like(P())) | (t.contact_name.like(P())) | (t.email.like(P())))
        qc = qc.where((t.business_name.like(P())) | (t.contact_name.like(P())) | (t.email.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.business_name, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 4. add-wholesale-price
# ===========================================================================
def add_wholesale_price(conn, args):
    _validate_company(conn, args.company_id)

    wholesale_rate = getattr(args, "wholesale_rate", None)
    if not wholesale_rate:
        err("--wholesale-rate is required")

    wc_id = getattr(args, "wholesale_customer_id", None)
    if wc_id:
        _get_wholesale_customer(conn, wc_id)

    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    wp_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("retailclaw_wholesale_price", {"id": P(), "wholesale_customer_id": P(), "item_id": P(), "item_name": P(), "wholesale_rate": P(), "min_order_qty": P(), "currency": P(), "valid_from": P(), "valid_to": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        wp_id, wc_id, item_id,
        getattr(args, "item_name", None),
        str(round_currency(to_decimal(wholesale_rate))),
        int(getattr(args, "min_order_qty", None) or 1),
        getattr(args, "currency", None) or "USD",
        getattr(args, "valid_from", None),
        getattr(args, "valid_to", None),
        args.company_id, now, now,
    ))
    audit(conn, "retailclaw_wholesale_price", wp_id, "retail-add-wholesale-price", args.company_id)
    conn.commit()
    ok({"id": wp_id, "wholesale_rate": str(round_currency(to_decimal(wholesale_rate)))})


# ===========================================================================
# 5. list-wholesale-prices
# ===========================================================================
def list_wholesale_prices(conn, args):
    t = Table("retailclaw_wholesale_price")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "wholesale_customer_id", None):
        q = q.where(t.wholesale_customer_id == P())
        qc = qc.where(t.wholesale_customer_id == P())
        params.append(args.wholesale_customer_id)
    if getattr(args, "item_id", None):
        q = q.where(t.item_id == P())
        qc = qc.where(t.item_id == P())
        params.append(args.item_id)
    if getattr(args, "search", None):
        q = q.where(t.item_name.like(P()))
        qc = qc.where(t.item_name.like(P()))
        params.append(f"%{args.search}%")

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 6. add-wholesale-order
# ===========================================================================
def add_wholesale_order(conn, args):
    _validate_company(conn, args.company_id)

    wc_id = getattr(args, "wholesale_customer_id", None)
    _get_wholesale_customer(conn, wc_id)

    order_date = getattr(args, "order_date", None)
    if not order_date:
        err("--order-date is required")

    wo_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_wholesale_order", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_wholesale_order", {"id": P(), "naming_series": P(), "wholesale_customer_id": P(), "order_date": P(), "expected_delivery_date": P(), "subtotal": P(), "discount_amount": P(), "tax_amount": P(), "total": P(), "notes": P(), "order_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        wo_id, naming, wc_id, order_date,
        getattr(args, "expected_delivery_date", None),
        "0.00", "0.00", "0.00", "0.00",
        getattr(args, "notes", None),
        "draft", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_wholesale_order", wo_id, "retail-add-wholesale-order", args.company_id)
    conn.commit()
    ok({"id": wo_id, "naming_series": naming, "order_status": "draft"})


# ===========================================================================
# 7. get-wholesale-order
# ===========================================================================
def get_wholesale_order(conn, args):
    order_id = getattr(args, "wholesale_order_id", None)
    if not order_id:
        err("--wholesale-order-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_wholesale_order")).select(Table("retailclaw_wholesale_order").star).where(Field("id") == P()).get_sql(), (order_id,)).fetchone()
    if not row:
        err(f"Wholesale order {order_id} not found")
    data = row_to_dict(row)

    items = conn.execute(Q.from_(Table("retailclaw_wholesale_order_item")).select(Table("retailclaw_wholesale_order_item").star).where(Field("order_id") == P()).orderby(Field("created_at"), order=Order.asc).get_sql(), (order_id,)).fetchall()
    data["items"] = [row_to_dict(i) for i in items]
    data["item_count"] = len(items)
    ok(data)


# ===========================================================================
# 8. list-wholesale-orders
# ===========================================================================
def list_wholesale_orders(conn, args):
    t = Table("retailclaw_wholesale_order")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "wholesale_customer_id", None):
        q = q.where(t.wholesale_customer_id == P())
        qc = qc.where(t.wholesale_customer_id == P())
        params.append(args.wholesale_customer_id)
    if getattr(args, "order_status", None):
        q = q.where(t.order_status == P())
        qc = qc.where(t.order_status == P())
        params.append(args.order_status)
    if getattr(args, "search", None):
        q = q.where((t.naming_series.like(P())) | (t.notes.like(P())))
        qc = qc.where((t.naming_series.like(P())) | (t.notes.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.order_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 9. add-wholesale-order-item
# ===========================================================================
def add_wholesale_order_item(conn, args):
    order_id = getattr(args, "wholesale_order_id", None)
    if not order_id:
        err("--wholesale-order-id is required")
    order_row = conn.execute(Q.from_(Table("retailclaw_wholesale_order")).select(Table("retailclaw_wholesale_order").star).where(Field("id") == P()).get_sql(), (order_id,)).fetchone()
    if not order_row:
        err(f"Wholesale order {order_id} not found")

    item_name = getattr(args, "item_name", None)
    if not item_name:
        err("--item-name is required")

    rate = getattr(args, "rate", None)
    if not rate:
        err("--rate is required")

    qty = int(getattr(args, "qty", None) or 1)
    rate_dec = round_currency(to_decimal(rate))
    amount_dec = round_currency(rate_dec * Decimal(str(qty)))

    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    oi_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("retailclaw_wholesale_order_item", {"id": P(), "order_id": P(), "item_id": P(), "item_name": P(), "qty": P(), "rate": P(), "amount": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        oi_id, order_id, item_id, item_name, qty,
        str(rate_dec), str(amount_dec),
        getattr(args, "notes", None),
        now, now,
    ))

    # Recalculate order totals
    woi = Table("retailclaw_wholesale_order_item")
    total_rows = conn.execute(
        Q.from_(woi).select(fn.Coalesce(fn.Sum(LiteralValue("CAST(amount AS REAL)")), 0)).where(woi.order_id == P()).get_sql(),
        (order_id,)
    ).fetchone()
    new_subtotal = round_currency(to_decimal(str(total_rows[0])))
    sql, upd_params = dynamic_update("retailclaw_wholesale_order", {
        "subtotal": str(new_subtotal),
        "total": str(new_subtotal),
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": order_id})
    conn.execute(sql, upd_params)

    audit(conn, "retailclaw_wholesale_order_item", oi_id, "retail-add-wholesale-order-item", None)
    conn.commit()
    ok({"id": oi_id, "order_id": order_id, "item_name": item_name, "qty": qty, "rate": str(rate_dec), "amount": str(amount_dec)})


# ===========================================================================
# 10. list-wholesale-order-items
# ===========================================================================
def list_wholesale_order_items(conn, args):
    t = Table("retailclaw_wholesale_order_item")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "wholesale_order_id", None):
        q = q.where(t.order_id == P())
        qc = qc.where(t.order_id == P())
        params.append(args.wholesale_order_id)
    if getattr(args, "item_id", None):
        q = q.where(t.item_id == P())
        qc = qc.where(t.item_id == P())
        params.append(args.item_id)

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.created_at, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-add-wholesale-customer": add_wholesale_customer,
    "retail-update-wholesale-customer": update_wholesale_customer,
    "retail-list-wholesale-customers": list_wholesale_customers,
    "retail-add-wholesale-price": add_wholesale_price,
    "retail-list-wholesale-prices": list_wholesale_prices,
    "retail-add-wholesale-order": add_wholesale_order,
    "retail-get-wholesale-order": get_wholesale_order,
    "retail-list-wholesale-orders": list_wholesale_orders,
    "retail-add-wholesale-order-item": add_wholesale_order_item,
    "retail-list-wholesale-order-items": list_wholesale_order_items,
}
