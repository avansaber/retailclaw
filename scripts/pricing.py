"""RetailClaw -- pricing domain module

Actions for pricing & promotions (4 tables, 12 actions).
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

    ENTITY_PREFIXES.setdefault("retailclaw_price_list", "RPL-")
    ENTITY_PREFIXES.setdefault("retailclaw_promotion", "PROMO-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_PRICE_LIST_TYPES = ("selling", "buying", "transfer")
VALID_PRICE_LIST_STATUSES = ("active", "inactive", "archived")
VALID_PROMO_TYPES = ("bogo", "percentage", "fixed", "bundle", "tiered")
VALID_PROMO_STATUSES = ("draft", "active", "paused", "expired", "cancelled")
VALID_COUPON_DISCOUNT_TYPES = ("percentage", "fixed")
VALID_COUPON_STATUSES = ("active", "used", "expired", "cancelled")


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


# ===========================================================================
# 1. add-price-list
# ===========================================================================
def add_price_list(conn, args):
    _validate_company(conn, args.company_id)
    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    price_list_type = getattr(args, "price_list_type", None) or "selling"
    _validate_enum(price_list_type, VALID_PRICE_LIST_TYPES, "price-list-type")

    pl_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_price_list", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_price_list", {"id": P(), "naming_series": P(), "name": P(), "description": P(), "currency": P(), "price_list_type": P(), "is_default": P(), "valid_from": P(), "valid_to": P(), "status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        pl_id, naming, name,
        getattr(args, "description", None),
        getattr(args, "currency", None) or "USD",
        price_list_type,
        int(getattr(args, "is_default", None) or 0),
        getattr(args, "valid_from", None),
        getattr(args, "valid_to", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_price_list", pl_id, "retail-add-price-list", args.company_id)
    conn.commit()
    ok({"id": pl_id, "naming_series": naming, "name": name, "price_list_status": "active"})


# ===========================================================================
# 2. update-price-list
# ===========================================================================
def update_price_list(conn, args):
    pl_id = getattr(args, "price_list_id", None)
    if not pl_id:
        err("--price-list-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_price_list")).select(Field("id")).where(Field("id") == P()).get_sql(), (pl_id,)).fetchone():
        err(f"Price list {pl_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "name": "name", "description": "description",
        "currency": "currency", "valid_from": "valid_from", "valid_to": "valid_to",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    price_list_type = getattr(args, "price_list_type", None)
    if price_list_type is not None:
        _validate_enum(price_list_type, VALID_PRICE_LIST_TYPES, "price-list-type")
        data["price_list_type"] = price_list_type
        changed.append("price_list_type")

    price_list_status = getattr(args, "price_list_status", None)
    if price_list_status is not None:
        _validate_enum(price_list_status, VALID_PRICE_LIST_STATUSES, "status")
        data["status"] = price_list_status
        changed.append("status")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_price_list", data, where={"id": pl_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_price_list", pl_id, "retail-update-price-list", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": pl_id, "updated_fields": changed})


# ===========================================================================
# 3. get-price-list
# ===========================================================================
def get_price_list(conn, args):
    pl_id = getattr(args, "price_list_id", None)
    if not pl_id:
        err("--price-list-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_price_list")).select(Table("retailclaw_price_list").star).where(Field("id") == P()).get_sql(), (pl_id,)).fetchone()
    if not row:
        err(f"Price list {pl_id} not found")
    data = row_to_dict(row)
    # item count
    item_count = conn.execute(Q.from_(Table("retailclaw_price_list_item")).select(fn.Count("*")).where(Field("price_list_id") == P()).get_sql(), (pl_id,)).fetchone()[0]
    data["item_count"] = item_count
    ok(data)


# ===========================================================================
# 4. list-price-lists
# ===========================================================================
def list_price_lists(conn, args):
    t = Table("retailclaw_price_list")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "status", None):
        q = q.where(t.status == P())
        qc = qc.where(t.status == P())
        params.append(args.status)
    if getattr(args, "search", None):
        q = q.where((t.name.like(P())) | (t.description.like(P())))
        qc = qc.where((t.name.like(P())) | (t.description.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 5. add-price-list-item
# ===========================================================================
def add_price_list_item(conn, args):
    pl_id = getattr(args, "price_list_id", None)
    if not pl_id:
        err("--price-list-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_price_list")).select(Field("id")).where(Field("id") == P()).get_sql(), (pl_id,)).fetchone():
        err(f"Price list {pl_id} not found")

    rate = getattr(args, "rate", None)
    if not rate:
        err("--rate is required")

    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    pli_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("retailclaw_price_list_item", {"id": P(), "price_list_id": P(), "item_id": P(), "item_name": P(), "rate": P(), "min_qty": P(), "currency": P(), "valid_from": P(), "valid_to": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        pli_id, pl_id, item_id,
        getattr(args, "item_name", None),
        str(round_currency(to_decimal(rate))),
        str(to_decimal(getattr(args, "min_qty", None) or "1")),
        getattr(args, "currency", None) or "USD",
        getattr(args, "valid_from", None),
        getattr(args, "valid_to", None),
        now, now,
    ))
    audit(conn, "retailclaw_price_list_item", pli_id, "retail-add-price-list-item", None)
    conn.commit()
    ok({"id": pli_id, "price_list_id": pl_id, "rate": str(round_currency(to_decimal(rate)))})


# ===========================================================================
# 6. update-price-list-item
# ===========================================================================
def update_price_list_item(conn, args):
    pli_id = getattr(args, "price_list_item_id", None)
    if not pli_id:
        err("--price-list-item-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_price_list_item")).select(Field("id")).where(Field("id") == P()).get_sql(), (pli_id,)).fetchone():
        err(f"Price list item {pli_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "item_name": "item_name", "currency": "currency",
        "valid_from": "valid_from", "valid_to": "valid_to",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    rate = getattr(args, "rate", None)
    if rate is not None:
        data["rate"] = str(round_currency(to_decimal(rate)))
        changed.append("rate")

    min_qty = getattr(args, "min_qty", None)
    if min_qty is not None:
        data["min_qty"] = str(to_decimal(min_qty))
        changed.append("min_qty")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_price_list_item", data, where={"id": pli_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_price_list_item", pli_id, "retail-update-price-list-item", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": pli_id, "updated_fields": changed})


# ===========================================================================
# 7. list-price-list-items
# ===========================================================================
def list_price_list_items(conn, args):
    t = Table("retailclaw_price_list_item")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "price_list_id", None):
        q = q.where(t.price_list_id == P())
        qc = qc.where(t.price_list_id == P())
        params.append(args.price_list_id)
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
# 8. add-promotion
# ===========================================================================
def add_promotion(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    promo_type = getattr(args, "promo_type", None)
    if not promo_type:
        err("--promo-type is required")
    _validate_enum(promo_type, VALID_PROMO_TYPES, "promo-type")

    start_date = getattr(args, "start_date", None)
    if not start_date:
        err("--start-date is required")
    end_date = getattr(args, "end_date", None)
    if not end_date:
        err("--end-date is required")

    discount_value = getattr(args, "discount_value", None) or "0"

    promo_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_promotion", company_id=args.company_id)
    now = _now_iso()

    max_uses = getattr(args, "max_uses", None)
    max_uses_val = int(max_uses) if max_uses else None

    sql, _ = insert_row("retailclaw_promotion", {"id": P(), "naming_series": P(), "name": P(), "description": P(), "promo_type": P(), "discount_value": P(), "min_purchase": P(), "max_discount": P(), "max_uses": P(), "used_count": P(), "applicable_items": P(), "applicable_categories": P(), "start_date": P(), "end_date": P(), "promo_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        promo_id, naming, name,
        getattr(args, "description", None),
        promo_type,
        str(round_currency(to_decimal(discount_value))),
        str(round_currency(to_decimal(getattr(args, "min_purchase", None) or "0"))),
        getattr(args, "max_discount", None),
        max_uses_val, 0,
        getattr(args, "applicable_items", None),
        getattr(args, "applicable_categories", None),
        start_date, end_date,
        "draft", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_promotion", promo_id, "retail-add-promotion", args.company_id)
    conn.commit()
    ok({"id": promo_id, "naming_series": naming, "name": name, "promo_status": "draft"})


# ===========================================================================
# 9. update-promotion
# ===========================================================================
def update_promotion(conn, args):
    promo_id = getattr(args, "promotion_id", None)
    if not promo_id:
        err("--promotion-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_promotion")).select(Field("id")).where(Field("id") == P()).get_sql(), (promo_id,)).fetchone():
        err(f"Promotion {promo_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "name": "name", "description": "description",
        "start_date": "start_date", "end_date": "end_date",
        "applicable_items": "applicable_items",
        "applicable_categories": "applicable_categories",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    promo_type = getattr(args, "promo_type", None)
    if promo_type is not None:
        _validate_enum(promo_type, VALID_PROMO_TYPES, "promo-type")
        data["promo_type"] = promo_type
        changed.append("promo_type")

    discount_value = getattr(args, "discount_value", None)
    if discount_value is not None:
        data["discount_value"] = str(round_currency(to_decimal(discount_value)))
        changed.append("discount_value")

    min_purchase = getattr(args, "min_purchase", None)
    if min_purchase is not None:
        data["min_purchase"] = str(round_currency(to_decimal(min_purchase)))
        changed.append("min_purchase")

    max_uses = getattr(args, "max_uses", None)
    if max_uses is not None:
        data["max_uses"] = int(max_uses)
        changed.append("max_uses")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_promotion", data, where={"id": promo_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_promotion", promo_id, "retail-update-promotion", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": promo_id, "updated_fields": changed})


# ===========================================================================
# 10. list-promotions
# ===========================================================================
def list_promotions(conn, args):
    t = Table("retailclaw_promotion")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "promo_status", None):
        q = q.where(t.promo_status == P())
        qc = qc.where(t.promo_status == P())
        params.append(args.promo_status)
    if getattr(args, "promo_type", None):
        q = q.where(t.promo_type == P())
        qc = qc.where(t.promo_type == P())
        params.append(args.promo_type)
    if getattr(args, "search", None):
        q = q.where((t.name.like(P())) | (t.description.like(P())))
        qc = qc.where((t.name.like(P())) | (t.description.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 11. activate-promotion
# ===========================================================================
def activate_promotion(conn, args):
    promo_id = getattr(args, "promotion_id", None)
    if not promo_id:
        err("--promotion-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_promotion")).select(Field("promo_status")).where(Field("id") == P()).get_sql(), (promo_id,)).fetchone()
    if not row:
        err(f"Promotion {promo_id} not found")
    if row[0] not in ("draft", "paused"):
        err(f"Cannot activate promotion in status '{row[0]}'. Must be draft or paused.")

    sql, upd_params = dynamic_update("retailclaw_promotion", {
        "promo_status": "active",
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": promo_id})
    conn.execute(sql, upd_params)
    audit(conn, "retailclaw_promotion", promo_id, "retail-activate-promotion", None)
    conn.commit()
    ok({"id": promo_id, "promo_status": "active"})


# ===========================================================================
# 12. deactivate-promotion
# ===========================================================================
def deactivate_promotion(conn, args):
    promo_id = getattr(args, "promotion_id", None)
    if not promo_id:
        err("--promotion-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_promotion")).select(Field("promo_status")).where(Field("id") == P()).get_sql(), (promo_id,)).fetchone()
    if not row:
        err(f"Promotion {promo_id} not found")
    if row[0] != "active":
        err(f"Cannot deactivate promotion in status '{row[0]}'. Must be active.")

    sql, upd_params = dynamic_update("retailclaw_promotion", {
        "promo_status": "paused",
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": promo_id})
    conn.execute(sql, upd_params)
    audit(conn, "retailclaw_promotion", promo_id, "retail-deactivate-promotion", None)
    conn.commit()
    ok({"id": promo_id, "promo_status": "paused"})


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-add-price-list": add_price_list,
    "retail-update-price-list": update_price_list,
    "retail-get-price-list": get_price_list,
    "retail-list-price-lists": list_price_lists,
    "retail-add-price-list-item": add_price_list_item,
    "retail-update-price-list-item": update_price_list_item,
    "retail-list-price-list-items": list_price_list_items,
    "retail-add-promotion": add_promotion,
    "retail-update-promotion": update_promotion,
    "retail-list-promotions": list_promotions,
    "retail-activate-promotion": activate_promotion,
    "retail-deactivate-promotion": deactivate_promotion,
}
