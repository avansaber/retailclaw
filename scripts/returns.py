"""RetailClaw -- returns & exchanges domain module

Actions for return authorizations, return items, and exchanges (3 tables, 8 actions).
GL posting for returns/refunds is required for a completed return that moves money: the refund ledger posts in the same transaction or the return is refused and rolled back.
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

try:
    import importlib.util
    if importlib.util.find_spec("erpclaw_lib") is None:
        sys.path.insert(0, os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.naming import get_next_name, ENTITY_PREFIXES
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, LiteralValue, insert_row, update_row, dynamic_update, now

    ENTITY_PREFIXES.setdefault("retailclaw_return_authorization", "RMA-")
except ImportError:
    pass

try:
    from erpclaw_lib.gl_posting import insert_gl_entries, reverse_gl_entries
    HAS_GL = True
except ImportError:
    HAS_GL = False

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SKILL = "retailclaw"

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
    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone():
        err(f"Company {company_id} not found")


def _validate_enum(value, valid_values, field_name):
    if value and value not in valid_values:
        err(f"Invalid {field_name}: {value}. Must be one of: {', '.join(valid_values)}")


def _get_return(conn, return_id):
    if not return_id:
        err("--return-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_return_authorization")).select(Table("retailclaw_return_authorization").star).where(Field("id") == P()).get_sql(), (return_id,)).fetchone()
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
        if not conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (customer_id,)).fetchone():
            err(f"Customer {customer_id} not found")

    ra_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_return_authorization", company_id=args.company_id)
    _ts = _now_iso()

    sql, _ = insert_row("retailclaw_return_authorization", {"id": P(), "naming_series": P(), "customer_id": P(), "customer_name": P(), "return_date": P(), "reason": P(), "return_type": P(), "original_invoice_id": P(), "subtotal": P(), "restocking_fee": P(), "refund_amount": P(), "notes": P(), "return_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        ra_id, naming, customer_id,
        getattr(args, "customer_name", None),
        return_date,
        getattr(args, "reason", None),
        return_type,
        getattr(args, "original_invoice_id", None),
        "0.00", "0.00", "0.00",
        getattr(args, "notes", None),
        "pending", args.company_id, _ts, _ts,
    ))
    audit(conn, SKILL, "retail-add-return-authorization", "retailclaw_return_authorization", ra_id)
    conn.commit()
    ok({"id": ra_id, "naming_series": naming, "return_status": "pending", "return_type": return_type})


# ===========================================================================
# 2. update-return-authorization
# ===========================================================================
def update_return_authorization(conn, args):
    return_id = getattr(args, "return_id", None)
    stored_status = row_to_dict(_get_return(conn, return_id)).get("return_status")

    data, changed = {}, []
    for arg_name, col_name in {
        "customer_name": "customer_name", "reason": "reason",
        "original_invoice_id": "original_invoice_id", "notes": "notes",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    return_type = getattr(args, "return_type", None)
    if return_type is not None:
        _validate_enum(return_type, VALID_RETURN_TYPES, "return-type")
        data["return_type"] = return_type
        changed.append("return_type")

    return_status = getattr(args, "return_status", None)
    if return_status is not None:
        _validate_enum(return_status, VALID_RETURN_STATUSES, "return-status")
        data["return_status"] = return_status
        changed.append("return_status")

    restocking_fee = getattr(args, "restocking_fee", None)
    if restocking_fee is not None:
        data["restocking_fee"] = str(round_currency(to_decimal(restocking_fee)))
        changed.append("restocking_fee")

    if stored_status == "completed" and set(data) != {"notes"}:
        err(f"Return {return_id} is completed and its refund is posted; it cannot be changed")
    if return_status == "completed":
        err("A return is completed only by retail-process-return, which posts its refund")
    if stored_status == "cancelled" and return_status is not None and return_status != "cancelled":
        err(f"Return {return_id} is cancelled and cannot be reopened")

    if not data:
        err("No fields to update")

    data["updated_at"] = now()
    sql, params = dynamic_update("retailclaw_return_authorization", data, where={"id": return_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "retail-update-return-authorization", "retailclaw_return_authorization",
          return_id, new_values={"updated_fields": changed})
    conn.commit()
    ok({"id": return_id, "updated_fields": changed})


# ===========================================================================
# 3. get-return-authorization
# ===========================================================================
def get_return_authorization(conn, args):
    return_id = getattr(args, "return_id", None)
    row = _get_return(conn, return_id)
    data = row_to_dict(row)

    items = conn.execute(Q.from_(Table("retailclaw_return_item")).select(Table("retailclaw_return_item").star).where(Field("return_id") == P()).orderby(Field("created_at"), order=Order.asc).get_sql(), (return_id,)).fetchall()
    data["items"] = [row_to_dict(i) for i in items]
    data["item_count"] = len(items)

    exchanges = conn.execute(Q.from_(Table("retailclaw_exchange")).select(Table("retailclaw_exchange").star).where(Field("return_id") == P()).orderby(Field("created_at"), order=Order.asc).get_sql(), (return_id,)).fetchall()
    data["exchanges"] = [row_to_dict(e) for e in exchanges]
    ok(data)


# ===========================================================================
# 4. list-return-authorizations
# ===========================================================================
def list_return_authorizations(conn, args):
    t = Table("retailclaw_return_authorization")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "customer_id", None):
        q = q.where(t.customer_id == P())
        qc = qc.where(t.customer_id == P())
        params.append(args.customer_id)
    if getattr(args, "return_status", None):
        q = q.where(t.return_status == P())
        qc = qc.where(t.return_status == P())
        params.append(args.return_status)
    if getattr(args, "return_type", None):
        q = q.where(t.return_type == P())
        qc = qc.where(t.return_type == P())
        params.append(args.return_type)
    if getattr(args, "search", None):
        q = q.where((t.customer_name.like(P())) | (t.naming_series.like(P())) | (t.reason.like(P())))
        qc = qc.where((t.customer_name.like(P())) | (t.naming_series.like(P())) | (t.reason.like(P())))
        params.extend([f"%{args.search}%", f"%{args.search}%", f"%{args.search}%"])

    total = conn.execute(qc.get_sql(), params).fetchone()[0]
    q = q.orderby(t.return_date, order=Order.desc).limit(P()).offset(P())
    rows = conn.execute(q.get_sql(), params + [args.limit, args.offset]).fetchall()
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
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (item_id,)).fetchone():
            err(f"Item {item_id} not found")

    ri_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("retailclaw_return_item", {"id": P(), "return_id": P(), "item_id": P(), "item_name": P(), "qty": P(), "rate": P(), "amount": P(), "reason": P(), "item_condition": P(), "disposition": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        ri_id, return_id, item_id, item_name, qty,
        str(rate_dec), str(amount_dec),
        getattr(args, "reason", None),
        item_condition, disposition, _ts, _ts,
    ))

    # Recalculate return subtotal and refund
    ri = Table("retailclaw_return_item")
    total_rows = conn.execute(
        Q.from_(ri).select(fn.Coalesce(fn.Sum(LiteralValue("CAST(amount AS NUMERIC)")), 0)).where(ri.return_id == P()).get_sql(),
        (return_id,)
    ).fetchone()
    new_subtotal = round_currency(to_decimal(str(total_rows[0])))
    restocking = to_decimal(
        conn.execute(Q.from_(Table("retailclaw_return_authorization")).select(Field("restocking_fee")).where(Field("id") == P()).get_sql(), (return_id,)).fetchone()[0]
    )
    refund = round_currency(new_subtotal - restocking) if new_subtotal > restocking else Decimal("0.00")
    sql, upd_params = dynamic_update("retailclaw_return_authorization", {
        "subtotal": str(new_subtotal),
        "refund_amount": str(refund),
        "updated_at": now(),
    }, where={"id": return_id})
    conn.execute(sql, upd_params)

    audit(conn, SKILL, "retail-add-return-item", "retailclaw_return_item", ri_id)
    conn.commit()
    ok({"id": ri_id, "return_id": return_id, "item_name": item_name, "qty": qty, "amount": str(amount_dec)})


# ===========================================================================
# 6. list-return-items
# ===========================================================================
def list_return_items(conn, args):
    t = Table("retailclaw_return_item")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "return_id", None):
        q = q.where(t.return_id == P())
        qc = qc.where(t.return_id == P())
        params.append(args.return_id)
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


# ===========================================================================
# GL Posting helpers
# ===========================================================================
def _build_refund_gl_entries(data, args):
    """Build GL entries for a return/refund.

    GL pattern for retail returns:
        DR: Sales Returns & Allowances  (refund_amount)
        CR: Cash / Accounts Receivable  (refund_amount)

    The restock pair is not posted, because it needs a stock ledger entry.
    Callers refuse restock flags before any write, so reaching here with a
    positive refund and missing accounts cannot happen.

    Returns the primary pair when the refund is positive, else [].
    All amounts are str (Decimal text).
    """
    refund_amount = to_decimal(data.get("refund_amount", "0"))
    if refund_amount <= Decimal("0"):
        return []

    sales_returns_account_id = getattr(args, "sales_returns_account_id", None)
    cash_account_id = getattr(args, "cash_account_id", None)
    cost_center_id = getattr(args, "cost_center_id", None)
    customer_id = data.get("customer_id")

    refund_str = str(round_currency(refund_amount))

    return [
        {
            "account_id": sales_returns_account_id,
            "debit": refund_str,
            "credit": "0",
            "cost_center_id": cost_center_id,
        },
        {
            "account_id": cash_account_id,
            "debit": "0",
            "credit": refund_str,
            "party_type": "customer" if customer_id else None,
            "party_id": customer_id if customer_id else None,
        },
    ]


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
    item_count = conn.execute(Q.from_(Table("retailclaw_return_item")).select(fn.Count("*")).where(Field("return_id") == P()).get_sql(), (return_id,)).fetchone()[0]
    if item_count == 0:
        err("No items in this return authorization. Add items first.")

    new_status = getattr(args, "return_status", None) or "completed"
    _validate_enum(new_status, VALID_RETURN_STATUSES, "return-status")

    if new_status == "completed":
        refund = to_decimal(data["refund_amount"])
        if (getattr(args, "inventory_account_id", None) is not None
                or getattr(args, "cogs_account_id", None) is not None
                or getattr(args, "restock_cost", None) is not None):
            err("restock posting is not supported: it would move a stock account with no stock ledger entry; complete the return without --inventory-account-id, --cogs-account-id and --restock-cost")
        if refund > 0 and (not getattr(args, "sales_returns_account_id", None) or not getattr(args, "cash_account_id", None)):
            err("--sales-returns-account-id and --cash-account-id are required to complete a return with a refund")
        if refund > 0 and not HAS_GL:
            err("GL posting is not available; a return with a refund cannot be completed")

    sql, upd_params = dynamic_update("retailclaw_return_authorization", {
        "return_status": new_status,
        "updated_at": now(),
    }, where={"id": return_id})
    conn.execute(sql, upd_params)

    # Ledger posts in the same transaction or the return is refused.
    gl_ids = []

    if new_status == "completed":
        try:
            primary_entries = _build_refund_gl_entries(data, args)
            posting_date = data.get("return_date", _now_iso()[:10])
            company_id = data["company_id"]

            # Post primary refund GL entries (Sales Returns DR / Cash CR)
            if primary_entries:
                primary_ids = insert_gl_entries(
                    conn,
                    primary_entries,
                    voucher_type="journal_entry",
                    voucher_id=return_id,
                    posting_date=posting_date,
                    company_id=company_id,
                    remarks=f"RetailClaw return refund: {data.get('naming_series', return_id)}",
                    entry_set="primary",
                )
                gl_ids.extend(primary_ids)

            # Store GL entry IDs on the return authorization
            if gl_ids:
                sql_gl, gl_params = dynamic_update("retailclaw_return_authorization", {
                    "gl_entry_ids": json.dumps(gl_ids),
                    "updated_at": now(),
                }, where={"id": return_id})
                conn.execute(sql_gl, gl_params)
        except Exception as e:
            conn.rollback()
            err(f"GL posting failed, return rolled back: {e}")

    audit(conn, SKILL, "retail-process-return", "retailclaw_return_authorization", return_id)
    conn.commit()

    result = {
        "id": return_id,
        "return_status": new_status,
        "subtotal": data["subtotal"],
        "restocking_fee": data["restocking_fee"],
        "refund_amount": data["refund_amount"],
        "items_processed": item_count,
    }
    if gl_ids:
        result["gl_entry_ids"] = gl_ids
    ok(result)


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
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (original_item_id,)).fetchone():
            err(f"Original item {original_item_id} not found")

    new_item_id = getattr(args, "new_item_id", None)
    if new_item_id:
        if not conn.execute(Q.from_(Table("item")).select(Field("id")).where(Field("id") == P()).get_sql(), (new_item_id,)).fetchone():
            err(f"New item {new_item_id} not found")

    price_difference = getattr(args, "price_difference", None) or "0"

    ex_id = str(uuid.uuid4())
    _ts = _now_iso()
    sql, _ = insert_row("retailclaw_exchange", {"id": P(), "return_id": P(), "original_item_id": P(), "original_item_name": P(), "new_item_id": P(), "new_item_name": P(), "qty": P(), "price_difference": P(), "exchange_status": P(), "notes": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        ex_id, return_id, original_item_id,
        getattr(args, "original_item_name", None),
        new_item_id, new_item_name,
        int(getattr(args, "qty", None) or 1),
        str(round_currency(to_decimal(price_difference))),
        "pending",
        getattr(args, "notes", None),
        args.company_id, _ts, _ts,
    ))
    audit(conn, SKILL, "retail-add-exchange", "retailclaw_exchange", ex_id)
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
