"""RetailClaw -- returns & exchanges domain module

Actions for return authorizations, return items, and exchanges (3 tables, 8 actions).
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

    ENTITY_PREFIXES.setdefault("retailclaw_return_authorization", "RMA-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_RETURN_TYPES = ("refund", "exchange", "store_credit")
VALID_RETURN_STATUSES = ("pending", "approved", "received", "inspected", "completed", "rejected", "cancelled")
VALID_ITEM_CONDITIONS = ("good", "damaged", "defective", "opened", "sealed")
VALID_DISPOSITIONS = ("restock", "dispose", "vendor_return", "refurbish")
VALID_EXCHANGE_STATUSES = ("pending", "completed", "cancelled")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    if not conn.execute("SELECT id FROM company WHERE id = ?", (company_id,)).fetchone():
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _get_return(conn, return_id):
    if not return_id:
        err("--return-id is required")
    row = conn.execute("SELECT * FROM retailclaw_return_authorization WHERE id = ?", (return_id,)).fetchone()
    if not row:
        err(f"Return authorization {return_id} not found")
    return row


# ===========================================================================
# 1. add-return-authorization
# ===========================================================================
def add_return_authorization(conn, args):
    _validate_company(conn, args.company_id)

    return_date = getattr(args, "return_date", None)
    if not return_date:
        err("--return-date is required")

    return_type = getattr(args, "return_type", None) or "refund"
    _validate_enum(return_type, VALID_RETURN_TYPES, "return-type")

    customer_id = getattr(args, "customer_id", None)
    if customer_id:
        if not conn.execute("SELECT id FROM customer WHERE id = ?", (customer_id,)).fetchone():
            err(f"Customer {customer_id} not found")

    ra_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_return_authorization", company_id=args.company_id)
    now = _now_iso()

    conn.execute("""
        INSERT INTO retailclaw_return_authorization (
            id, naming_series, customer_id, customer_name, return_date, reason,
            return_type, original_invoice_id, subtotal, restocking_fee, refund_amount,
            notes, return_status, company_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ra_id, naming, customer_id,
        getattr(args, "customer_name", None),
        return_date,
        getattr(args, "reason", None),
        return_type,
        getattr(args, "original_invoice_id", None),
        "0.00", "0.00", "0.00",
        getattr(args, "notes", None),
        "pending", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_return_authorization", ra_id, "retail-add-return-authorization", args.company_id)
    conn.commit()
    ok({"id": ra_id, "naming_series": naming, "return_status": "pending", "return_type": return_type})


# ===========================================================================
# 2. update-return-authorization
# ===========================================================================
def update_return_authorization(conn, args):
    return_id = getattr(args, "return_id", None)
    _get_return(conn, return_id)

    updates, params, changed = [], [], []
    for arg_name, col_name in {
        "customer_name": "customer_name", "reason": "reason",
        "original_invoice_id": "original_invoice_id", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            updates.append(f"{col_name} = ?")
            params.append(val)
            changed.append(col_name)

    return_type = getattr(args, "return_type", None)
    if return_type is not None:
        _validate_enum(return_type, VALID_RETURN_TYPES, "return-type")
        updates.append("return_type = ?")
        params.append(return_type)
        changed.append("return_type")

    return_status = getattr(args, "return_status", None)
    if return_status is not None:
        _validate_enum(return_status, VALID_RETURN_STATUSES, "return-status")
        updates.append("return_status = ?")
        params.append(return_status)
        changed.append("return_status")

    restocking_fee = getattr(args, "restocking_fee", None)
    if restocking_fee is not None:
        updates.append("restocking_fee = ?")
        params.append(str(round_currency(to_decimal(restocking_fee))))
        changed.append("restocking_fee")

    if not updates:
        err("No fields to update")

    updates.append("updated_at = datetime('now')")
    params.append(return_id)
    conn.execute(f"UPDATE retailclaw_return_authorization SET {', '.join(updates)} WHERE id = ?", params)
    audit(conn, "retailclaw_return_authorization", return_id, "retail-update-return-authorization", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": return_id, "updated_fields": changed})


# ===========================================================================
# 3. get-return-authorization
# ===========================================================================
def get_return_authorization(conn, args):
    return_id = getattr(args, "return_id", None)
    row = _get_return(conn, return_id)
    data = row_to_dict(row)

    items = conn.execute(
        "SELECT * FROM retailclaw_return_item WHERE return_id = ? ORDER BY created_at ASC",
        (return_id,)
    ).fetchall()
    data["items"] = [row_to_dict(i) for i in items]
    data["item_count"] = len(items)

    exchanges = conn.execute(
        "SELECT * FROM retailclaw_exchange WHERE return_id = ? ORDER BY created_at ASC",
        (return_id,)
    ).fetchall()
    data["exchanges"] = [row_to_dict(e) for e in exchanges]
    ok(data)


# ===========================================================================
# 4. list-return-authorizations
# ===========================================================================
def list_return_authorizations(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "customer_id", None):
        where.append("customer_id = ?")
        params.append(args.customer_id)
    if getattr(args, "return_status", None):
        where.append("return_status = ?")
        params.append(args.return_status)
    if getattr(args, "return_type", None):
        where.append("return_type = ?")
        params.append(args.return_type)
    if getattr(args, "search", None):
        where.append("(customer_name LIKE ? OR naming_series LIKE ? OR reason LIKE ?)")
        params.extend([f"%{args.search}%", f"%{args.search}%", f"%{args.search}%"])

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM retailclaw_return_authorization WHERE {where_sql}", params).fetchone()[0]
    params.extend([args.limit, args.offset])
    rows = conn.execute(
        f"SELECT * FROM retailclaw_return_authorization WHERE {where_sql} ORDER BY return_date DESC LIMIT ? OFFSET ?",
        params
    ).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 5. add-return-item
# ===========================================================================
def add_return_item(conn, args):
    return_id = getattr(args, "return_id", None)
    _get_return(conn, return_id)

    item_name = getattr(args, "item_name", None)
    if not item_name:
        err("--item-name is required")

    rate = getattr(args, "rate", None)
    if not rate:
        err("--rate is required")

    qty = int(getattr(args, "qty", None) or 1)
    rate_dec = round_currency(to_decimal(rate))
    amount_dec = round_currency(rate_dec * Decimal(str(qty)))

    item_condition = getattr(args, "item_condition", None) or "good"
    _validate_enum(item_condition, VALID_ITEM_CONDITIONS, "item-condition")

    disposition = getattr(args, "disposition", None) or "restock"
    _validate_enum(disposition, VALID_DISPOSITIONS, "disposition")

    item_id = getattr(args, "item_id", None)
    if item_id:
        if not conn.execute("SELECT id FROM item WHERE id = ?", (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    ri_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute("""
        INSERT INTO retailclaw_return_item (
            id, return_id, item_id, item_name, qty, rate, amount,
            reason, item_condition, disposition, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ri_id, return_id, item_id, item_name, qty,
        str(rate_dec), str(amount_dec),
        getattr(args, "reason", None),
        item_condition, disposition, now, now,
    ))

    # Recalculate return subtotal and refund
    total_rows = conn.execute(
        "SELECT COALESCE(SUM(CAST(amount AS REAL)), 0) FROM retailclaw_return_item WHERE return_id = ?",
        (return_id,)
    ).fetchone()
    new_subtotal = round_currency(to_decimal(str(total_rows[0])))
    restocking = to_decimal(
        conn.execute("SELECT restocking_fee FROM retailclaw_return_authorization WHERE id = ?", (return_id,)).fetchone()[0]
    )
    refund = round_currency(new_subtotal - restocking) if new_subtotal > restocking else Decimal("0.00")
    conn.execute(
        "UPDATE retailclaw_return_authorization SET subtotal = ?, refund_amount = ?, updated_at = datetime('now') WHERE id = ?",
        (str(new_subtotal), str(refund), return_id)
    )

    audit(conn, "retailclaw_return_item", ri_id, "retail-add-return-item", None)
    conn.commit()
    ok({"id": ri_id, "return_id": return_id, "item_name": item_name, "qty": qty, "amount": str(amount_dec)})


# ===========================================================================
# 6. list-return-items
# ===========================================================================
def list_return_items(conn, args):
    where, params = ["1=1"], []
    if getattr(args, "return_id", None):
        where.append("return_id = ?")
        params.append(args.return_id)
    if getattr(args, "item_id", None):
        where.append("item_id = ?")
        params.append(args.item_id)

    where_sql = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM retailclaw_return_item WHERE {where_sql}", params).fetchone()[0]
    params.extend([args.limit, args.offset])
    rows = conn.execute(
        f"SELECT * FROM retailclaw_return_item WHERE {where_sql} ORDER BY created_at ASC LIMIT ? OFFSET ?",
        params
    ).fetchall()
    ok({
        "rows": [row_to_dict(r) for r in rows],
        "total_count": total, "limit": args.limit, "offset": args.offset,
        "has_more": (args.offset + args.limit) < total,
    })


# ===========================================================================
# 7. process-return
# ===========================================================================
def process_return(conn, args):
    return_id = getattr(args, "return_id", None)
    row = _get_return(conn, return_id)
    data = row_to_dict(row)

    current_status = data["return_status"]
    if current_status in ("completed", "cancelled"):
        err(f"Return is already {current_status}. Cannot process.")

    # Count items
    item_count = conn.execute(
        "SELECT COUNT(*) FROM retailclaw_return_item WHERE return_id = ?", (return_id,)
    ).fetchone()[0]
    if item_count == 0:
        err("No items in this return authorization. Add items first.")

    new_status = getattr(args, "return_status", None) or "completed"
    _validate_enum(new_status, VALID_RETURN_STATUSES, "return-status")

    conn.execute(
        "UPDATE retailclaw_return_authorization SET return_status = ?, updated_at = datetime('now') WHERE id = ?",
        (new_status, return_id)
    )
    audit(conn, "retailclaw_return_authorization", return_id, "retail-process-return", None)
    conn.commit()
    ok({
        "id": return_id,
        "return_status": new_status,
        "subtotal": data["subtotal"],
        "restocking_fee": data["restocking_fee"],
        "refund_amount": data["refund_amount"],
        "items_processed": item_count,
    })


# ===========================================================================
# 8. add-exchange
# ===========================================================================
def add_exchange(conn, args):
    _validate_company(conn, args.company_id)

    return_id = getattr(args, "return_id", None)
    _get_return(conn, return_id)

    new_item_name = getattr(args, "new_item_name", None)
    if not new_item_name:
        err("--new-item-name is required")

    original_item_id = getattr(args, "original_item_id", None)
    if original_item_id:
        if not conn.execute("SELECT id FROM item WHERE id = ?", (original_item_id,)).fetchone():
            err(f"Original item {original_item_id} not found")

    new_item_id = getattr(args, "new_item_id", None)
    if new_item_id:
        if not conn.execute("SELECT id FROM item WHERE id = ?", (new_item_id,)).fetchone():
            err(f"New item {new_item_id} not found")

    price_difference = getattr(args, "price_difference", None) or "0"

    ex_id = str(uuid.uuid4())
    now = _now_iso()
    conn.execute("""
        INSERT INTO retailclaw_exchange (
            id, return_id, original_item_id, original_item_name,
            new_item_id, new_item_name, qty, price_difference,
            exchange_status, notes, company_id, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        ex_id, return_id, original_item_id,
        getattr(args, "original_item_name", None),
        new_item_id, new_item_name,
        int(getattr(args, "qty", None) or 1),
        str(round_currency(to_decimal(price_difference))),
        "pending",
        getattr(args, "notes", None),
        args.company_id, now, now,
    ))
    audit(conn, "retailclaw_exchange", ex_id, "retail-add-exchange", args.company_id)
    conn.commit()
    ok({"id": ex_id, "return_id": return_id, "new_item_name": new_item_name, "exchange_status": "pending"})


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-add-return-authorization": add_return_authorization,
    "retail-update-return-authorization": update_return_authorization,
    "retail-get-return-authorization": get_return_authorization,
    "retail-list-return-authorizations": list_return_authorizations,
    "retail-add-return-item": add_return_item,
    "retail-list-return-items": list_return_items,
    "retail-process-return": process_return,
    "retail-add-exchange": add_exchange,
}
