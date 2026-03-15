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
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row

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

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "name": "name", "description": "description",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    sort_order = getattr(args, "sort_order", None)
    if sort_order is not None:
        updates.append("sort_order = ?")
        params.append(int(sort_order))
        changed.append("sort_order")

    is_active = getattr(args, "is_active", None)
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(int(is_active))
        changed.append("is_active")

    parent_id = getattr(args, "parent_id", None)
    if parent_id is not None:
        if parent_id and parent_id != cat_id:
            if not conn.execute(Q.from_(Table("retailclaw_category")).select(Field("id")).where(Field("id") == P()).get_sql(), (parent_id,)).fetchone():
                err(f"Parent category {parent_id} not found")
        elif parent_id == cat_id:
            err("Category cannot be its own parent")
        updates.append("parent_id = ?")
        params.append(parent_id if parent_id else None)
        changed.append("parent_id")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(cat_id)
    conn.execute(f"UPDATE retailclaw_category SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "retailclaw_category", cat_id, "retail-update-category", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": cat_id, "updated_fields": changed})


# ===========================================================================
# 3. list-categories
# ===========================================================================
def list_categories(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "parent_id", None):
        where.append("parent_id = ?")
        params.append(args.parent_id)
    if getattr(args, "search", None):
        where.append("(name LIKE ? OR description LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM retailclaw_category WHERE {where_sql}", params).fetchone()[0]
    params.extend([args.limit, args.offset])
    rows = conn.execute(
        f"SELECT * FROM retailclaw_category WHERE {where_sql} ORDER BY sort_order ASC, name ASC LIMIT ? OFFSET ?",
        params
    ).fetchall()
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

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "name": "name", "description": "description",
        "store_section": "store_section", "fixture_type": "fixture_type",
        "effective_date": "effective_date",
        "width_inches": "width_inches", "height_inches": "height_inches",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    shelf_count = getattr(args, "shelf_count", None)
    if shelf_count is not None:
        updates.append("shelf_count = ?")
        params.append(int(shelf_count))
        changed.append("shelf_count")

    planogram_status = getattr(args, "planogram_status", None)
    if planogram_status is not None:
        _validate_enum(planogram_status, VALID_PLANOGRAM_STATUSES, "planogram-status")
        updates.append("planogram_status = ?")
        params.append(planogram_status)
        changed.append("planogram_status")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(plano_id)
    conn.execute(f"UPDATE retailclaw_planogram SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "retailclaw_planogram", plano_id, "retail-update-planogram", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": plano_id, "updated_fields": changed})


# ===========================================================================
# 6. list-planograms
# ===========================================================================
def list_planograms(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "planogram_status", None):
        where.append("planogram_status = ?")
        params.append(args.planogram_status)
    if getattr(args, "search", None):
        where.append("(name LIKE ? OR description LIKE ? OR store_section LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%", f"%{args.search}%"])

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM retailclaw_planogram WHERE {where_sql}", params).fetchone()[0]
    params.extend([args.limit, args.offset])
    rows = conn.execute(
        f"SELECT * FROM retailclaw_planogram WHERE {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params
    ).fetchall()
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
    where, params = ["1=1"], []
    if getattr(args, "planogram_id", None):
        where.append("planogram_id = ?")
        params.append(args.planogram_id)
    if getattr(args, "item_id", None):
        where.append("item_id = ?")
        params.append(args.item_id)
    if getattr(args, "search", None):
        where.append("(item_name LIKE ? OR notes LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%"])

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM retailclaw_planogram_item WHERE {where_sql}", params).fetchone()[0]
    params.extend([args.limit, args.offset])
    rows = conn.execute(
        f"SELECT * FROM retailclaw_planogram_item WHERE {where_sql} ORDER BY shelf_number ASC, position ASC LIMIT ? OFFSET ?",
        params
    ).fetchall()
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
