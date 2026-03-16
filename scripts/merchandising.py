"""RetailClaw -- merchandising domain module

Actions for categories, planograms, and displays (4 tables, 8 actions).
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

    ENTITY_PREFIXES.setdefault("retailclaw_planogram", "PLANO-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_PLANOGRAM_STATUSES = ("draft", "active", "archived")
VALID_DISPLAY_TYPES = ("endcap", "island", "window", "counter", "pegboard", "shelf", "floor", "wall")
VALID_DISPLAY_STATUSES = ("planned", "active", "inactive", "archived")


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
# 1. add-category
# ===========================================================================
def add_category(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    parent_id = getattr(args, "parent_id", None)
    if parent_id:
        if not conn.execute(Q.from_(Table("retailclaw_category")).select(Field("id")).where(Field("id") == P()).get_sql(), (parent_id,)).fetchone():
            err(f"Parent category {parent_id} not found")

    cat_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("retailclaw_category", {"id": P(), "name": P(), "parent_id": P(), "description": P(), "sort_order": P(), "is_active": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        cat_id, name, parent_id,
        getattr(args, "description", None),
        int(getattr(args, "sort_order", None) or 0),
        1, args.company_id, now, now,
    ))
    audit(conn, "retailclaw_category", cat_id, "retail-add-category", args.company_id)
    conn.commit()
    ok({"id": cat_id, "name": name, "parent_id": parent_id})


# ===========================================================================
# 2. update-category
# ===========================================================================
def update_category(conn, args):
    cat_id = getattr(args, "category_id", None)
    if not cat_id:
        err("--category-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_category")).select(Field("id")).where(Field("id") == P()).get_sql(), (cat_id,)).fetchone():
        err(f"Category {cat_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "name": "name", "description": "description",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    sort_order = getattr(args, "sort_order", None)
    if sort_order is not None:
        data["sort_order"] = int(sort_order)
        changed.append("sort_order")

    is_active = getattr(args, "is_active", None)
    if is_active is not None:
        data["is_active"] = int(is_active)
        changed.append("is_active")

    parent_id = getattr(args, "parent_id", None)
    if parent_id is not None:
        if parent_id and parent_id != cat_id:
            if not conn.execute(Q.from_(Table("retailclaw_category")).select(Field("id")).where(Field("id") == P()).get_sql(), (parent_id,)).fetchone():
                err(f"Parent category {parent_id} not found")
        elif parent_id == cat_id:
            err("Category cannot be its own parent")
        data["parent_id"] = parent_id if parent_id else None
        changed.append("parent_id")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_category", data, where={"id": cat_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_category", cat_id, "retail-update-category", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": cat_id, "updated_fields": changed})


# ===========================================================================
# 3. list-categories
# ===========================================================================
def list_categories(conn, args):
    t = Table("retailclaw_category")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "parent_id", None):
        q = q.where(t.parent_id == P())
        qc = qc.where(t.parent_id == P())
        params.append(args.parent_id)
    if getattr(args, "search", None):
        q = q.where((t.name.like(P())) | (t.description.like(P())))
        qc = qc.where((t.name.like(P())) | (t.description.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.sort_order, order=Order.asc).orderby(t.name, order=Order.asc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 4. add-planogram
# ===========================================================================
def add_planogram(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    plano_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_planogram", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_planogram", {"id": P(), "naming_series": P(), "name": P(), "description": P(), "store_section": P(), "fixture_type": P(), "shelf_count": P(), "width_inches": P(), "height_inches": P(), "planogram_status": P(), "effective_date": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        plano_id, naming, name,
        getattr(args, "description", None),
        getattr(args, "store_section", None),
        getattr(args, "fixture_type", None),
        int(getattr(args, "shelf_count", None) or 1),
        getattr(args, "width_inches", None),
        getattr(args, "height_inches", None),
        "draft",
        getattr(args, "effective_date", None),
        args.company_id, now, now,
    ))
    audit(conn, "retailclaw_planogram", plano_id, "retail-add-planogram", args.company_id)
    conn.commit()
    ok({"id": plano_id, "naming_series": naming, "name": name, "planogram_status": "draft"})


# ===========================================================================
# 5. update-planogram
# ===========================================================================
def update_planogram(conn, args):
    plano_id = getattr(args, "planogram_id", None)
    if not plano_id:
        err("--planogram-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_planogram")).select(Field("id")).where(Field("id") == P()).get_sql(), (plano_id,)).fetchone():
        err(f"Planogram {plano_id} not found")

    data, changed = {}, []
    for arg_name, col_name in {
        "name": "name", "description": "description",
        "store_section": "store_section", "fixture_type": "fixture_type",
        "effective_date": "effective_date",
        "width_inches": "width_inches", "height_inches": "height_inches",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    shelf_count = getattr(args, "shelf_count", None)
    if shelf_count is not None:
        data["shelf_count"] = int(shelf_count)
        changed.append("shelf_count")

    planogram_status = getattr(args, "planogram_status", None)
    if planogram_status is not None:
        _validate_enum(planogram_status, VALID_PLANOGRAM_STATUSES, "planogram-status")
        data["planogram_status"] = planogram_status
        changed.append("planogram_status")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_planogram", data, where={"id": plano_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_planogram", plano_id, "retail-update-planogram", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": plano_id, "updated_fields": changed})


# ===========================================================================
# 6. list-planograms
# ===========================================================================
def list_planograms(conn, args):
    t = Table("retailclaw_planogram")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "planogram_status", None):
        q = q.where(t.planogram_status == P())
        qc = qc.where(t.planogram_status == P())
        params.append(args.planogram_status)
    if getattr(args, "search", None):
        q = q.where((t.name.like(P())) | (t.description.like(P())) | (t.store_section.like(P())))
        qc = qc.where((t.name.like(P())) | (t.description.like(P())) | (t.store_section.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.created_at, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 7. add-planogram-item
# ===========================================================================
def add_planogram_item(conn, args):
    plano_id = getattr(args, "planogram_id", None)
    if not plano_id:
        err("--planogram-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_planogram")).select(Field("id")).where(Field("id") == P()).get_sql(), (plano_id,)).fetchone():
        err(f"Planogram {plano_id} not found")

    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    pi_id = str(uuid.uuid4())
    now = _now_iso()
    sql, _ = insert_row("retailclaw_planogram_item", {"id": P(), "planogram_id": P(), "item_id": P(), "item_name": P(), "shelf_number": P(), "position": P(), "facings": P(), "min_stock": P(), "max_stock": P(), "notes": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        pi_id, plano_id, item_id,
        getattr(args, "item_name", None),
        int(getattr(args, "shelf_number", None) or 1),
        int(getattr(args, "position", None) or 1),
        int(getattr(args, "facings", None) or 1),
        int(getattr(args, "min_stock", None) or 0),
        int(getattr(args, "max_stock", None)) if getattr(args, "max_stock", None) else None,
        getattr(args, "notes", None),
        now, now,
    ))
    audit(conn, "retailclaw_planogram_item", pi_id, "retail-add-planogram-item", None)
    conn.commit()
    ok({"id": pi_id, "planogram_id": plano_id, "item_name": getattr(args, "item_name", None)})


# ===========================================================================
# 8. list-planogram-items
# ===========================================================================
def list_planogram_items(conn, args):
    t = Table("retailclaw_planogram_item")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "planogram_id", None):
        q = q.where(t.planogram_id == P())
        qc = qc.where(t.planogram_id == P())
        params.append(args.planogram_id)
    if getattr(args, "item_id", None):
        q = q.where(t.item_id == P())
        qc = qc.where(t.item_id == P())
        params.append(args.item_id)
    if getattr(args, "search", None):
        q = q.where((t.item_name.like(P())) | (t.notes.like(P())))
        qc = qc.where((t.item_name.like(P())) | (t.notes.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.shelf_number, order=Order.asc).orderby(t.position, order=Order.asc).limit(P()).offset(P())
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
    "retail-add-category": add_category,
    "retail-update-category": update_category,
    "retail-list-categories": list_categories,
    "retail-add-planogram": add_planogram,
    "retail-update-planogram": update_planogram,
    "retail-list-planograms": list_planograms,
    "retail-add-planogram-item": add_planogram_item,
    "retail-list-planogram-items": list_planogram_items,
}
