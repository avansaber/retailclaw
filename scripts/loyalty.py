"""RetailClaw -- loyalty domain module

Actions for customer loyalty programs (4 tables, 12 actions).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
import uuid
import secrets
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

    ENTITY_PREFIXES.setdefault("retailclaw_loyalty_program", "LPROG-")
    ENTITY_PREFIXES.setdefault("retailclaw_loyalty_member", "LMEM-")
    ENTITY_PREFIXES.setdefault("retailclaw_gift_card", "GC-")
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ---------------------------------------------------------------------------
# Validation constants
# ---------------------------------------------------------------------------
VALID_PROGRAM_STATUSES = ("active", "inactive", "archived")
VALID_MEMBER_TIERS = ("bronze", "silver", "gold", "platinum")
VALID_MEMBER_STATUSES = ("active", "inactive", "suspended", "cancelled")
VALID_TXN_TYPES = ("earn", "redeem", "adjust", "expire", "bonus")
VALID_CARD_STATUSES = ("active", "redeemed", "expired", "cancelled")


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


def _get_member(conn, member_id):
    if not member_id:
        err("--member-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_loyalty_member")).select(Table("retailclaw_loyalty_member").star).where(Field("id") == P()).get_sql(), (member_id,)).fetchone()
    if not row:
        err(f"Loyalty member {member_id} not found")
    return row


# ===========================================================================
# 1. add-loyalty-program
# ===========================================================================
def add_loyalty_program(conn, args):
    _validate_company(conn, args.company_id)

    name = getattr(args, "name", None)
    if not name:
        err("--name is required")

    prog_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_loyalty_program", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_loyalty_program", {"id": P(), "naming_series": P(), "name": P(), "description": P(), "points_per_dollar": P(), "redemption_rate": P(), "tiers": P(), "program_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        prog_id, naming, name,
        getattr(args, "description", None),
        str(to_decimal(getattr(args, "points_per_dollar", None) or "1")),
        str(to_decimal(getattr(args, "redemption_rate", None) or "0.01")),
        getattr(args, "tiers", None) or "[]",
        "active", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_loyalty_program", prog_id, "retail-add-loyalty-program", args.company_id)
    conn.commit()
    ok({"id": prog_id, "naming_series": naming, "name": name, "program_status": "active"})


# ===========================================================================
# 2. get-loyalty-program
# ===========================================================================
def get_loyalty_program(conn, args):
    prog_id = getattr(args, "program_id", None)
    if not prog_id:
        err("--program-id is required")
    row = conn.execute(Q.from_(Table("retailclaw_loyalty_program")).select(Table("retailclaw_loyalty_program").star).where(Field("id") == P()).get_sql(), (prog_id,)).fetchone()
    if not row:
        err(f"Loyalty program {prog_id} not found")
    data = row_to_dict(row)
    member_count = conn.execute(Q.from_(Table("retailclaw_loyalty_member")).select(fn.Count("*")).where(Field("program_id") == P()).get_sql(), (prog_id,)).fetchone()[0]
    data["member_count"] = member_count
    ok(data)


# ===========================================================================
# 3. list-loyalty-programs
# ===========================================================================
def list_loyalty_programs(conn, args):
    t = Table("retailclaw_loyalty_program")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "program_status", None):
        q = q.where(t.program_status == P())
        qc = qc.where(t.program_status == P())
        params.append(args.program_status)
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
# 4. add-loyalty-member
# ===========================================================================
def add_loyalty_member(conn, args):
    _validate_company(conn, args.company_id)

    program_id = getattr(args, "program_id", None)
    if not program_id:
        err("--program-id is required")
    if not conn.execute(Q.from_(Table("retailclaw_loyalty_program")).select(Field("id")).where(Field("id") == P()).get_sql(), (program_id,)).fetchone():
        err(f"Loyalty program {program_id} not found")

    customer_name = getattr(args, "customer_name", None)
    if not customer_name:
        err("--customer-name is required")

    enrollment_date = getattr(args, "enrollment_date", None)
    if not enrollment_date:
        err("--enrollment-date is required")

    customer_id = getattr(args, "customer_id", None)
    if customer_id:
        if not conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (customer_id,)).fetchone():
            err(f"Customer {customer_id} not found")

    mem_id = str(uuid.uuid4())
    naming = get_next_name(conn, "retailclaw_loyalty_member", company_id=args.company_id)
    now = _now_iso()

    sql, _ = insert_row("retailclaw_loyalty_member", {"id": P(), "naming_series": P(), "program_id": P(), "customer_id": P(), "customer_name": P(), "email": P(), "phone": P(), "member_tier": P(), "points_balance": P(), "lifetime_points": P(), "enrollment_date": P(), "last_activity_date": P(), "member_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        mem_id, naming, program_id, customer_id, customer_name,
        getattr(args, "email", None),
        getattr(args, "phone", None),
        getattr(args, "member_tier", None) or "bronze",
        0, 0, enrollment_date, None,
        "active", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_loyalty_member", mem_id, "retail-add-loyalty-member", args.company_id)
    conn.commit()
    ok({"id": mem_id, "naming_series": naming, "customer_name": customer_name, "member_tier": "bronze", "points_balance": 0})


# ===========================================================================
# 5. update-loyalty-member
# ===========================================================================
def update_loyalty_member(conn, args):
    member_id = getattr(args, "member_id", None)
    _get_member(conn, member_id)

    data, changed = {}, []
    for arg_name, col_name in {
        "customer_name": "customer_name", "email": "email", "phone": "phone",
    }.items():
        val = getattr(args, arg_name, None)
        if val is not None:
            data[col_name] = val
            changed.append(col_name)

    member_tier = getattr(args, "member_tier", None)
    if member_tier is not None:
        _validate_enum(member_tier, VALID_MEMBER_TIERS, "member-tier")
        data["member_tier"] = member_tier
        changed.append("member_tier")

    member_status = getattr(args, "member_status", None)
    if member_status is not None:
        _validate_enum(member_status, VALID_MEMBER_STATUSES, "member-status")
        data["member_status"] = member_status
        changed.append("member_status")

    if not data:
        err("No fields to update")

    data["updated_at"] = LiteralValue("datetime('now')")
    sql, params = dynamic_update("retailclaw_loyalty_member", data, where={"id": member_id})
    conn.execute(sql, params)
    audit(conn, "retailclaw_loyalty_member", member_id, "retail-update-loyalty-member", None, {"updated_fields": changed})
    conn.commit()
    ok({"id": member_id, "updated_fields": changed})


# ===========================================================================
# 6. get-loyalty-member
# ===========================================================================
def get_loyalty_member(conn, args):
    member_id = getattr(args, "member_id", None)
    row = _get_member(conn, member_id)
    data = row_to_dict(row)
    # Recent transactions
    txns = conn.execute(Q.from_(Table("retailclaw_loyalty_transaction")).select(Table("retailclaw_loyalty_transaction").star).where(Field("member_id") == P()).orderby(Field("created_at"), order=Order.desc).limit(10).get_sql(), (member_id,)).fetchall()
    data["recent_transactions"] = [row_to_dict(t) for t in txns]
    ok(data)


# ===========================================================================
# 7. list-loyalty-members
# ===========================================================================
def list_loyalty_members(conn, args):
    t = Table("retailclaw_loyalty_member")
    q = Q.from_(t).select(t.star)
    qc = Q.from_(t).select(fn.Count("*"))
    params = []
    if getattr(args, "company_id", None):
        q = q.where(t.company_id == P())
        qc = qc.where(t.company_id == P())
        params.append(args.company_id)
    if getattr(args, "program_id", None):
        q = q.where(t.program_id == P())
        qc = qc.where(t.program_id == P())
        params.append(args.program_id)
    if getattr(args, "member_tier", None):
        q = q.where(t.member_tier == P())
        qc = qc.where(t.member_tier == P())
        params.append(args.member_tier)
    if getattr(args, "member_status", None):
        q = q.where(t.member_status == P())
        qc = qc.where(t.member_status == P())
        params.append(args.member_status)
    if getattr(args, "search", None):
        q = q.where((t.customer_name.like(P())) | (t.email.like(P())))
        qc = qc.where((t.customer_name.like(P())) | (t.email.like(P())))
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
# 8. add-loyalty-points
# ===========================================================================
def add_loyalty_points(conn, args):
    member_id = getattr(args, "member_id", None)
    member = _get_member(conn, member_id)
    member_dict = row_to_dict(member)

    points = getattr(args, "points", None)
    if not points:
        err("--points is required")
    points_val = int(points)
    if points_val <= 0:
        err("Points must be positive")

    current_balance = int(member_dict["points_balance"])
    lifetime = int(member_dict["lifetime_points"])
    new_balance = current_balance + points_val
    new_lifetime = lifetime + points_val

    sql, upd_params = dynamic_update("retailclaw_loyalty_member", {
        "points_balance": new_balance,
        "lifetime_points": new_lifetime,
        "last_activity_date": LiteralValue("datetime('now')"),
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": member_id})
    conn.execute(sql, upd_params)

    txn_id = str(uuid.uuid4())
    sql, _ = insert_row("retailclaw_loyalty_transaction", {"id": P(), "member_id": P(), "transaction_type": P(), "points": P(), "balance_after": P(), "reference_type": P(), "reference_id": P(), "description": P(), "created_at": P()})
    conn.execute(sql, (
        txn_id, member_id, "earn", points_val, new_balance,
        getattr(args, "reference_type", None),
        getattr(args, "reference_id", None),
        getattr(args, "description", None) or f"Earned {points_val} points",
        _now_iso(),
    ))
    audit(conn, "retailclaw_loyalty_member", member_id, "retail-add-loyalty-points", None)
    conn.commit()
    ok({"member_id": member_id, "points_added": points_val, "points_balance": new_balance, "lifetime_points": new_lifetime})


# ===========================================================================
# 9. redeem-loyalty-points
# ===========================================================================
def redeem_loyalty_points(conn, args):
    member_id = getattr(args, "member_id", None)
    member = _get_member(conn, member_id)
    member_dict = row_to_dict(member)

    points = getattr(args, "points", None)
    if not points:
        err("--points is required")
    points_val = int(points)
    if points_val <= 0:
        err("Points must be positive")

    current_balance = int(member_dict["points_balance"])
    if points_val > current_balance:
        err(f"Insufficient points. Balance: {current_balance}, requested: {points_val}")

    new_balance = current_balance - points_val

    sql, upd_params = dynamic_update("retailclaw_loyalty_member", {
        "points_balance": new_balance,
        "last_activity_date": LiteralValue("datetime('now')"),
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": member_id})
    conn.execute(sql, upd_params)

    txn_id = str(uuid.uuid4())
    sql, _ = insert_row("retailclaw_loyalty_transaction", {"id": P(), "member_id": P(), "transaction_type": P(), "points": P(), "balance_after": P(), "reference_type": P(), "reference_id": P(), "description": P(), "created_at": P()})
    conn.execute(sql, (
        txn_id, member_id, "redeem", -points_val, new_balance,
        getattr(args, "reference_type", None),
        getattr(args, "reference_id", None),
        getattr(args, "description", None) or f"Redeemed {points_val} points",
        _now_iso(),
    ))
    audit(conn, "retailclaw_loyalty_member", member_id, "retail-redeem-loyalty-points", None)
    conn.commit()
    ok({"member_id": member_id, "points_redeemed": points_val, "points_balance": new_balance})


# ===========================================================================
# 10. add-gift-card
# ===========================================================================
def add_gift_card(conn, args):
    _validate_company(conn, args.company_id)

    initial_balance = getattr(args, "initial_balance", None)
    if not initial_balance:
        err("--initial-balance is required")

    issue_date = getattr(args, "issue_date", None)
    if not issue_date:
        err("--issue-date is required")

    balance_dec = round_currency(to_decimal(initial_balance))

    gc_id = str(uuid.uuid4())
    card_number = getattr(args, "card_number", None) or f"GC-{secrets.token_hex(6).upper()}"
    now = _now_iso()

    sql, _ = insert_row("retailclaw_gift_card", {"id": P(), "card_number": P(), "initial_balance": P(), "current_balance": P(), "currency": P(), "purchaser_name": P(), "recipient_name": P(), "recipient_email": P(), "issue_date": P(), "expiration_date": P(), "card_status": P(), "company_id": P(), "created_at": P(), "updated_at": P()})
    conn.execute(sql, (
        gc_id, card_number,
        str(balance_dec), str(balance_dec),
        getattr(args, "currency", None) or "USD",
        getattr(args, "purchaser_name", None),
        getattr(args, "recipient_name", None),
        getattr(args, "recipient_email", None),
        issue_date,
        getattr(args, "expiration_date", None),
        "active", args.company_id, now, now,
    ))
    audit(conn, "retailclaw_gift_card", gc_id, "retail-add-gift-card", args.company_id)
    conn.commit()
    ok({"id": gc_id, "card_number": card_number, "initial_balance": str(balance_dec), "card_status": "active"})


# ===========================================================================
# 11. check-gift-card-balance
# ===========================================================================
def check_gift_card_balance(conn, args):
    card_number = getattr(args, "card_number", None)
    gc_id = getattr(args, "gift_card_id", None)

    if not card_number and not gc_id:
        err("--card-number or --gift-card-id is required")

    if gc_id:
        row = conn.execute(Q.from_(Table("retailclaw_gift_card")).select(Table("retailclaw_gift_card").star).where(Field("id") == P()).get_sql(), (gc_id,)).fetchone()
    else:
        row = conn.execute(Q.from_(Table("retailclaw_gift_card")).select(Table("retailclaw_gift_card").star).where(Field("card_number") == P()).get_sql(), (card_number,)).fetchone()

    if not row:
        err("Gift card not found")

    data = row_to_dict(row)
    ok({
        "card_number": data["card_number"],
        "initial_balance": data["initial_balance"],
        "current_balance": data["current_balance"],
        "card_status": data["card_status"],
        "expiration_date": data.get("expiration_date"),
    })


# ===========================================================================
# 12. redeem-gift-card
# ===========================================================================
def redeem_gift_card(conn, args):
    card_number = getattr(args, "card_number", None)
    gc_id = getattr(args, "gift_card_id", None)

    if not card_number and not gc_id:
        err("--card-number or --gift-card-id is required")

    if gc_id:
        row = conn.execute(Q.from_(Table("retailclaw_gift_card")).select(Table("retailclaw_gift_card").star).where(Field("id") == P()).get_sql(), (gc_id,)).fetchone()
    else:
        row = conn.execute(Q.from_(Table("retailclaw_gift_card")).select(Table("retailclaw_gift_card").star).where(Field("card_number") == P()).get_sql(), (card_number,)).fetchone()

    if not row:
        err("Gift card not found")

    data = row_to_dict(row)
    if data["card_status"] != "active":
        err(f"Gift card is {data['card_status']}. Cannot redeem.")

    amount = getattr(args, "amount", None)
    if not amount:
        err("--amount is required")

    amount_dec = round_currency(to_decimal(amount))
    current = to_decimal(data["current_balance"])

    if amount_dec > current:
        err(f"Insufficient balance. Current: {current}, requested: {amount_dec}")

    new_balance = round_currency(current - amount_dec)
    new_status = "redeemed" if new_balance == Decimal("0.00") else "active"

    actual_gc_id = data["id"]
    sql, upd_params = dynamic_update("retailclaw_gift_card", {
        "current_balance": str(new_balance),
        "card_status": new_status,
        "updated_at": LiteralValue("datetime('now')"),
    }, where={"id": actual_gc_id})
    conn.execute(sql, upd_params)
    audit(conn, "retailclaw_gift_card", actual_gc_id, "retail-redeem-gift-card", None)
    conn.commit()
    ok({
        "card_number": data["card_number"],
        "amount_redeemed": str(amount_dec),
        "current_balance": str(new_balance),
        "card_status": new_status,
    })


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-add-loyalty-program": add_loyalty_program,
    "retail-get-loyalty-program": get_loyalty_program,
    "retail-list-loyalty-programs": list_loyalty_programs,
    "retail-add-loyalty-member": add_loyalty_member,
    "retail-update-loyalty-member": update_loyalty_member,
    "retail-get-loyalty-member": get_loyalty_member,
    "retail-list-loyalty-members": list_loyalty_members,
    "retail-add-loyalty-points": add_loyalty_points,
    "retail-redeem-loyalty-points": redeem_loyalty_points,
    "retail-add-gift-card": add_gift_card,
    "retail-check-gift-card-balance": check_gift_card_balance,
    "retail-redeem-gift-card": redeem_gift_card,
}
