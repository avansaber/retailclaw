"""RetailClaw -- Procurement, Shift Scheduling, Shrinkage/Loss Prevention,
Barcode Labels, Customer Segmentation, Store Credit domain module.

17 actions across 6 gap areas:
R3: Retail Procurement (4 actions)
R4: Shift Scheduling (2 actions)
R5: Shrinkage/Loss Prevention (4 actions)
R6: Barcode Label Printing (1 action)
R7: Customer Segmentation (3 actions)
R10: Store Credit (3 actions)
"""
import json
import os
import sys
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, LiteralValue, insert_row, update_row, dynamic_update
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SKILL = "retailclaw"

_t_item = Table("item")
_t_store = Table("retailclaw_store_location")
_t_shrinkage = Table("retailclaw_shrinkage")
_t_credit = Table("retailclaw_store_credit")
_t_member = Table("retailclaw_loyalty_member")
_t_txn = Table("retailclaw_loyalty_transaction")

VALID_SHRINKAGE_CAUSES = ("theft", "damage", "spoilage", "admin_error", "vendor_fraud", "unknown")
VALID_CREDIT_SOURCES = ("return", "promotion", "adjustment", "gift")


def _d(val, default="0"):
    if val is None:
        return Decimal(default)
    return Decimal(str(val))


def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone():
        err(f"Company {company_id} not found")


# ===========================================================================
# R3: RETAIL PROCUREMENT
# ===========================================================================

def check_reorder_points(conn, args):
    """Compare stock vs reorder level per location."""
    _validate_company(conn, args.company_id)

    # Check items where current stock is at or below reorder level
    # Uses stock_ledger_entry or item reorder_level field
    rows = conn.execute(
        """SELECT i.id as item_id, i.item_name, i.item_code,
                  COALESCE(i.reorder_level, '0') as reorder_level,
                  COALESCE(
                      (SELECT SUM(CAST(actual_qty AS REAL))
                       FROM stock_ledger_entry
                       WHERE item_id = i.id),
                      0
                  ) as current_stock
           FROM item i
           WHERE i.company_id = ?
           AND i.is_stock_item = 1
           HAVING CAST(current_stock AS REAL) <= CAST(reorder_level AS REAL)
                  AND CAST(reorder_level AS REAL) > 0
           ORDER BY current_stock ASC""",
        (args.company_id,),
    ).fetchall()

    items = []
    for r in rows:
        items.append({
            "item_id": r["item_id"],
            "item_name": r["item_name"],
            "item_code": r["item_code"],
            "reorder_level": r["reorder_level"],
            "current_stock": str(round(r["current_stock"], 2)),
            "deficit": str(round(float(r["reorder_level"]) - r["current_stock"], 2)),
        })

    ok({
        "company_id": args.company_id,
        "items_below_reorder": len(items),
        "items": items,
    })


def generate_purchase_suggestions(conn, args):
    """Generate purchase suggestions for items below reorder levels."""
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT i.id as item_id, i.item_name, i.item_code,
                  COALESCE(i.reorder_level, '0') as reorder_level,
                  COALESCE(i.reorder_qty, '0') as reorder_qty,
                  COALESCE(i.standard_rate, '0') as standard_rate,
                  COALESCE(
                      (SELECT SUM(CAST(actual_qty AS REAL))
                       FROM stock_ledger_entry
                       WHERE item_id = i.id),
                      0
                  ) as current_stock
           FROM item i
           WHERE i.company_id = ?
           AND i.is_stock_item = 1
           HAVING CAST(current_stock AS REAL) <= CAST(reorder_level AS REAL)
                  AND CAST(reorder_level AS REAL) > 0
           ORDER BY item_name""",
        (args.company_id,),
    ).fetchall()

    suggestions = []
    total_cost = Decimal("0")
    for r in rows:
        reorder_qty = _d(r["reorder_qty"]) if _d(r["reorder_qty"]) > 0 else _d(r["reorder_level"])
        rate = _d(r["standard_rate"])
        est_cost = reorder_qty * rate
        total_cost += est_cost
        suggestions.append({
            "item_id": r["item_id"],
            "item_name": r["item_name"],
            "current_stock": str(round(r["current_stock"], 2)),
            "reorder_level": r["reorder_level"],
            "suggested_qty": str(reorder_qty),
            "estimated_cost": str(est_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "company_id": args.company_id,
        "suggestion_count": len(suggestions),
        "estimated_total_cost": str(total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "suggestions": suggestions,
    })


def auto_create_purchase_orders(conn, args):
    """Auto-create purchase orders from reorder suggestions (placeholder -- returns suggestions)."""
    _validate_company(conn, args.company_id)

    # This action generates the data for purchase orders. Actual PO creation
    # goes through erpclaw-buying module.
    rows = conn.execute(
        """SELECT i.id as item_id, i.item_name, i.item_code,
                  COALESCE(i.reorder_level, '0') as reorder_level,
                  COALESCE(i.reorder_qty, '0') as reorder_qty,
                  COALESCE(i.standard_rate, '0') as standard_rate,
                  COALESCE(i.default_supplier_id, '') as supplier_id,
                  COALESCE(
                      (SELECT SUM(CAST(actual_qty AS REAL))
                       FROM stock_ledger_entry
                       WHERE item_id = i.id),
                      0
                  ) as current_stock
           FROM item i
           WHERE i.company_id = ?
           AND i.is_stock_item = 1
           HAVING CAST(current_stock AS REAL) <= CAST(reorder_level AS REAL)
                  AND CAST(reorder_level AS REAL) > 0""",
        (args.company_id,),
    ).fetchall()

    # Group by supplier
    by_supplier = {}
    for r in rows:
        sid = r["supplier_id"] or "unassigned"
        by_supplier.setdefault(sid, []).append({
            "item_id": r["item_id"],
            "item_name": r["item_name"],
            "qty": str(_d(r["reorder_qty"]) if _d(r["reorder_qty"]) > 0 else _d(r["reorder_level"])),
            "rate": r["standard_rate"],
        })

    ok({
        "company_id": args.company_id,
        "purchase_order_groups": len(by_supplier),
        "groups": [{"supplier_id": k, "items": v} for k, v in by_supplier.items()],
        "note": "Use erpclaw-buying add-purchase-order to create actual POs",
    })


def procurement_report(conn, args):
    _validate_company(conn, args.company_id)

    total_items = conn.execute(
        "SELECT COUNT(*) as cnt FROM item WHERE company_id = ? AND is_stock_item = 1",
        (args.company_id,),
    ).fetchone()["cnt"]

    below_reorder = conn.execute(
        """SELECT COUNT(*) as cnt FROM item i
           WHERE i.company_id = ? AND i.is_stock_item = 1
           AND CAST(COALESCE(i.reorder_level, '0') AS REAL) > 0
           AND COALESCE(
               (SELECT SUM(CAST(actual_qty AS REAL)) FROM stock_ledger_entry WHERE item_id = i.id),
               0
           ) <= CAST(COALESCE(i.reorder_level, '0') AS REAL)""",
        (args.company_id,),
    ).fetchone()["cnt"]

    ok({
        "company_id": args.company_id,
        "total_stock_items": total_items,
        "items_below_reorder": below_reorder,
        "reorder_pct": str(round(below_reorder / total_items * 100, 1)) if total_items > 0 else "0.0",
    })


# ===========================================================================
# R4: SHIFT SCHEDULING (wrapper around core HR)
# ===========================================================================

def add_store_shift(conn, args):
    """Add a store shift -- wrapper that records a shift for a retail location."""
    _validate_company(conn, args.company_id)
    store_id = getattr(args, "store_location_id", None)
    if not store_id:
        err("--store-location-id is required")
    name = getattr(args, "name", None)
    if not name:
        err("--name is required (shift name, e.g., 'Morning', 'Evening')")

    # Verify store exists
    store = conn.execute(
        Q.from_(_t_store).select(_t_store.star).where(_t_store.id == P()).get_sql(),
        (store_id,),
    ).fetchone()
    if not store:
        err(f"Store location {store_id} not found")

    # Store shift as a note in audit for now; actual shift uses erpclaw core HR
    audit(conn, SKILL, "retail-add-store-shift", "retailclaw_store_location", store_id,
          new_values={"shift_name": name, "start_date": getattr(args, "start_date", None),
                      "end_date": getattr(args, "end_date", None)})
    conn.commit()
    ok({
        "store_location_id": store_id,
        "shift_name": name,
        "note": "Use erpclaw core add-shift-type for full shift management",
    })


def list_store_schedules(conn, args):
    """List store schedules (from audit trail)."""
    _validate_company(conn, args.company_id)

    store_id = getattr(args, "store_location_id", None)
    if store_id:
        # Verify it exists
        store = conn.execute(
            Q.from_(_t_store).select(_t_store.star).where(_t_store.id == P()).get_sql(),
            (store_id,),
        ).fetchone()
        if not store:
            err(f"Store location {store_id} not found")

    # Get stores
    q = Q.from_(_t_store).select(_t_store.star)
    params = []
    if args.company_id:
        q = q.where(_t_store.company_id == P())
        params.append(args.company_id)
    if store_id:
        q = q.where(_t_store.id == P())
        params.append(store_id)

    rows = conn.execute(q.get_sql(), params).fetchall()
    stores = [row_to_dict(r) for r in rows]

    ok({
        "store_count": len(stores),
        "stores": stores,
        "note": "Use erpclaw core list-shift-types for full schedule details",
    })


# ===========================================================================
# R5: SHRINKAGE / LOSS PREVENTION
# ===========================================================================

def record_shrinkage(conn, args):
    _validate_company(conn, args.company_id)
    quantity = getattr(args, "quantity", None)
    if not quantity:
        err("--quantity is required")
    cause = getattr(args, "cause", None)
    if not cause:
        err("--cause is required")
    if cause not in VALID_SHRINKAGE_CAUSES:
        err(f"Invalid cause: {cause}. Must be one of: {', '.join(VALID_SHRINKAGE_CAUSES)}")
    discovered_date = getattr(args, "discovered_date", None)
    if not discovered_date:
        err("--discovered-date is required")

    s_id = str(uuid.uuid4())
    n = _now_iso()
    sql, _ = insert_row("retailclaw_shrinkage", {
        "id": P(), "store_location_id": P(), "item_id": P(),
        "quantity": P(), "cause": P(), "discovered_date": P(),
        "reported_by": P(), "value_lost": P(), "notes": P(),
        "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        s_id,
        getattr(args, "store_location_id", None),
        getattr(args, "item_id", None),
        str(_d(quantity)),
        cause,
        discovered_date,
        getattr(args, "reported_by", None),
        str(_d(getattr(args, "value_lost", None))),
        getattr(args, "notes", None),
        args.company_id, n,
    ))
    audit(conn, SKILL, "retail-record-shrinkage",
          "retailclaw_shrinkage", s_id,
          new_values={"cause": cause, "quantity": quantity})
    conn.commit()
    ok({
        "shrinkage_id": s_id, "cause": cause,
        "quantity": str(_d(quantity)),
        "value_lost": str(_d(getattr(args, "value_lost", None))),
    })


def list_shrinkage(conn, args):
    t = _t_shrinkage
    q = Q.from_(t).select(t.star)
    params = []

    cid = getattr(args, "company_id", None)
    if cid:
        q = q.where(t.company_id == P())
        params.append(cid)
    store_id = getattr(args, "store_location_id", None)
    if store_id:
        q = q.where(t.store_location_id == P())
        params.append(store_id)
    cause = getattr(args, "cause", None)
    if cause:
        q = q.where(t.cause == P())
        params.append(cause)

    q = q.orderby(t.discovered_date, order=Order.desc).limit(P()).offset(P())
    limit = getattr(args, "limit", 50) or 50
    offset = getattr(args, "offset", 0) or 0
    rows = conn.execute(q.get_sql(), params + [limit, offset]).fetchall()
    ok({"shrinkage_records": [row_to_dict(r) for r in rows], "total_count": len(rows)})


def shrinkage_report(conn, args):
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT cause,
                  COUNT(*) as incident_count,
                  SUM(CAST(quantity AS REAL)) as total_qty,
                  SUM(CAST(value_lost AS REAL)) as total_value
           FROM retailclaw_shrinkage
           WHERE company_id = ?
           GROUP BY cause
           ORDER BY total_value DESC""",
        (args.company_id,),
    ).fetchall()

    causes = []
    grand_value = Decimal("0")
    grand_qty = Decimal("0")
    for r in rows:
        v = _d(r["total_value"])
        q = _d(r["total_qty"])
        grand_value += v
        grand_qty += q
        causes.append({
            "cause": r["cause"],
            "incident_count": r["incident_count"],
            "total_quantity": str(q.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "total_value_lost": str(v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        })

    ok({
        "company_id": args.company_id,
        "by_cause": causes,
        "grand_total_quantity": str(grand_qty.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "grand_total_value_lost": str(grand_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    })


def shrinkage_by_cause_report(conn, args):
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT s.*, sl.name as store_name
           FROM retailclaw_shrinkage s
           LEFT JOIN retailclaw_store_location sl ON s.store_location_id = sl.id
           WHERE s.company_id = ?
           ORDER BY s.discovered_date DESC""",
        (args.company_id,),
    ).fetchall()

    by_cause = {}
    for r in rows:
        cause = r["cause"]
        by_cause.setdefault(cause, []).append(row_to_dict(r))

    ok({
        "company_id": args.company_id,
        "total_incidents": len(rows),
        "by_cause": {k: {"count": len(v), "records": v} for k, v in by_cause.items()},
    })


# ===========================================================================
# R6: BARCODE LABEL PRINTING
# ===========================================================================

def generate_barcode_labels(conn, args):
    """Return label data for a batch of items: item name, SKU, UPC, price."""
    _validate_company(conn, args.company_id)

    # Get items -- optionally filter by category or search
    conditions = ["i.company_id = ?"]
    params = [args.company_id]
    search = getattr(args, "search", None)
    if search:
        conditions.append("(i.item_name LIKE ? OR i.item_code LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s])
    category_id = getattr(args, "category_id", None)
    if category_id:
        conditions.append("i.item_group = ?")
        params.append(category_id)

    where = f"WHERE {' AND '.join(conditions)}"
    limit = getattr(args, "limit", 50) or 50

    rows = conn.execute(
        f"""SELECT i.id, i.item_name, i.item_code,
                   COALESCE(i.barcode, '') as barcode,
                   COALESCE(i.standard_rate, '0') as standard_rate
            FROM item i
            {where}
            ORDER BY i.item_name
            LIMIT ?""",
        params + [limit],
    ).fetchall()

    labels = []
    for r in rows:
        labels.append({
            "item_id": r["id"],
            "item_name": r["item_name"],
            "sku": r["item_code"],
            "upc": r["barcode"],
            "price": r["standard_rate"],
        })

    ok({
        "company_id": args.company_id,
        "label_count": len(labels),
        "labels": labels,
    })


# ===========================================================================
# R7: CUSTOMER SEGMENTATION (RFM)
# ===========================================================================

def calculate_rfm(conn, args):
    """Recency/Frequency/Monetary analysis per customer."""
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT si.customer_id, c.name as customer_name,
                  MAX(si.posting_date) as last_purchase_date,
                  COUNT(*) as purchase_count,
                  SUM(CAST(si.grand_total AS REAL)) as total_spent
           FROM sales_invoice si
           JOIN customer c ON si.customer_id = c.id
           WHERE si.company_id = ? AND si.docstatus = 1
           GROUP BY si.customer_id
           ORDER BY total_spent DESC""",
        (args.company_id,),
    ).fetchall()

    today = date.today()
    segments = []
    for r in rows:
        last_date = r["last_purchase_date"]
        if last_date:
            try:
                ld = datetime.strptime(last_date, "%Y-%m-%d").date()
                recency_days = (today - ld).days
            except ValueError:
                recency_days = 999
        else:
            recency_days = 999

        total = _d(r["total_spent"])
        freq = r["purchase_count"]

        # Simple RFM scoring (1-5 scale)
        r_score = 5 if recency_days <= 30 else (4 if recency_days <= 60 else (3 if recency_days <= 90 else (2 if recency_days <= 180 else 1)))
        f_score = min(5, max(1, freq))
        m_score = 5 if total >= 10000 else (4 if total >= 5000 else (3 if total >= 1000 else (2 if total >= 100 else 1)))

        rfm_total = r_score + f_score + m_score
        if rfm_total >= 12:
            segment = "champion"
        elif rfm_total >= 9:
            segment = "loyal"
        elif rfm_total >= 6:
            segment = "potential"
        elif rfm_total >= 4:
            segment = "at_risk"
        else:
            segment = "dormant"

        segments.append({
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"],
            "recency_days": recency_days,
            "frequency": freq,
            "monetary": str(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "r_score": r_score,
            "f_score": f_score,
            "m_score": m_score,
            "rfm_total": rfm_total,
            "segment": segment,
        })

    ok({
        "company_id": args.company_id,
        "customer_count": len(segments),
        "segments": segments,
    })


def list_customer_segments(conn, args):
    """List aggregated customer segment counts."""
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT si.customer_id, c.name as customer_name,
                  MAX(si.posting_date) as last_purchase_date,
                  COUNT(*) as purchase_count,
                  SUM(CAST(si.grand_total AS REAL)) as total_spent
           FROM sales_invoice si
           JOIN customer c ON si.customer_id = c.id
           WHERE si.company_id = ? AND si.docstatus = 1
           GROUP BY si.customer_id""",
        (args.company_id,),
    ).fetchall()

    today = date.today()
    segment_counts = {"champion": 0, "loyal": 0, "potential": 0, "at_risk": 0, "dormant": 0}

    for r in rows:
        last_date = r["last_purchase_date"]
        if last_date:
            try:
                ld = datetime.strptime(last_date, "%Y-%m-%d").date()
                recency_days = (today - ld).days
            except ValueError:
                recency_days = 999
        else:
            recency_days = 999

        total = float(r["total_spent"] or 0)
        freq = r["purchase_count"]

        r_score = 5 if recency_days <= 30 else (4 if recency_days <= 60 else (3 if recency_days <= 90 else (2 if recency_days <= 180 else 1)))
        f_score = min(5, max(1, freq))
        m_score = 5 if total >= 10000 else (4 if total >= 5000 else (3 if total >= 1000 else (2 if total >= 100 else 1)))

        rfm_total = r_score + f_score + m_score
        if rfm_total >= 12:
            segment_counts["champion"] += 1
        elif rfm_total >= 9:
            segment_counts["loyal"] += 1
        elif rfm_total >= 6:
            segment_counts["potential"] += 1
        elif rfm_total >= 4:
            segment_counts["at_risk"] += 1
        else:
            segment_counts["dormant"] += 1

    ok({
        "company_id": args.company_id,
        "total_customers": len(rows),
        "segments": segment_counts,
    })


def segment_performance_report(conn, args):
    """Performance report by customer segment."""
    _validate_company(conn, args.company_id)

    rows = conn.execute(
        """SELECT si.customer_id, c.name as customer_name,
                  MAX(si.posting_date) as last_purchase_date,
                  COUNT(*) as purchase_count,
                  SUM(CAST(si.grand_total AS REAL)) as total_spent
           FROM sales_invoice si
           JOIN customer c ON si.customer_id = c.id
           WHERE si.company_id = ? AND si.docstatus = 1
           GROUP BY si.customer_id""",
        (args.company_id,),
    ).fetchall()

    today = date.today()
    segment_data = {
        "champion": {"count": 0, "revenue": Decimal("0"), "avg_frequency": 0},
        "loyal": {"count": 0, "revenue": Decimal("0"), "avg_frequency": 0},
        "potential": {"count": 0, "revenue": Decimal("0"), "avg_frequency": 0},
        "at_risk": {"count": 0, "revenue": Decimal("0"), "avg_frequency": 0},
        "dormant": {"count": 0, "revenue": Decimal("0"), "avg_frequency": 0},
    }

    for r in rows:
        last_date = r["last_purchase_date"]
        if last_date:
            try:
                ld = datetime.strptime(last_date, "%Y-%m-%d").date()
                recency_days = (today - ld).days
            except ValueError:
                recency_days = 999
        else:
            recency_days = 999

        total = _d(r["total_spent"])
        freq = r["purchase_count"]

        r_score = 5 if recency_days <= 30 else (4 if recency_days <= 60 else (3 if recency_days <= 90 else (2 if recency_days <= 180 else 1)))
        f_score = min(5, max(1, freq))
        m_score = 5 if total >= 10000 else (4 if total >= 5000 else (3 if total >= 1000 else (2 if total >= 100 else 1)))

        rfm_total = r_score + f_score + m_score
        if rfm_total >= 12:
            seg = "champion"
        elif rfm_total >= 9:
            seg = "loyal"
        elif rfm_total >= 6:
            seg = "potential"
        elif rfm_total >= 4:
            seg = "at_risk"
        else:
            seg = "dormant"

        segment_data[seg]["count"] += 1
        segment_data[seg]["revenue"] += total
        segment_data[seg]["avg_frequency"] += freq

    result = {}
    for seg, data in segment_data.items():
        avg_freq = data["avg_frequency"] / data["count"] if data["count"] > 0 else 0
        result[seg] = {
            "customer_count": data["count"],
            "total_revenue": str(data["revenue"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "avg_frequency": str(round(avg_freq, 1)),
        }

    ok({
        "company_id": args.company_id,
        "segments": result,
    })


# ===========================================================================
# R10: STORE CREDIT
# ===========================================================================

def issue_store_credit(conn, args):
    _validate_company(conn, args.company_id)
    customer_id = getattr(args, "customer_id", None)
    if not customer_id:
        err("--customer-id is required")
    amount = getattr(args, "amount", None)
    if not amount:
        err("--amount is required")

    source = getattr(args, "source", None)
    if source and source not in VALID_CREDIT_SOURCES:
        err(f"Invalid source: {source}. Must be one of: {', '.join(VALID_CREDIT_SOURCES)}")

    amt = _d(amount)
    sc_id = str(uuid.uuid4())
    n = _now_iso()
    sql, _ = insert_row("retailclaw_store_credit", {
        "id": P(), "customer_id": P(), "original_amount": P(),
        "remaining_balance": P(), "issued_date": P(), "expiration_date": P(),
        "source": P(), "source_reference_id": P(),
        "status": P(), "company_id": P(), "created_at": P(),
    })
    conn.execute(sql, (
        sc_id, customer_id, str(amt), str(amt),
        date.today().isoformat(),
        getattr(args, "expiration_date", None),
        source or "adjustment",
        getattr(args, "reference_id", None),
        "active",
        args.company_id, n,
    ))
    audit(conn, SKILL, "retail-issue-store-credit",
          "retailclaw_store_credit", sc_id,
          new_values={"customer_id": customer_id, "amount": str(amt)})
    conn.commit()
    ok({
        "store_credit_id": sc_id, "customer_id": customer_id,
        "amount": str(amt), "credit_status": "active",
    })


def redeem_store_credit(conn, args):
    sc_id = getattr(args, "store_credit_id", None)
    if not sc_id:
        err("--store-credit-id is required")
    amount = getattr(args, "amount", None)
    if not amount:
        err("--amount is required")

    row = conn.execute(
        Q.from_(_t_credit).select(_t_credit.star).where(_t_credit.id == P()).get_sql(),
        (sc_id,),
    ).fetchone()
    if not row:
        err(f"Store credit {sc_id} not found")
    if row["status"] != "active":
        err(f"Store credit is {row['status']}")

    redeem_amt = _d(amount)
    balance = _d(row["remaining_balance"])

    if redeem_amt > balance:
        err(f"Redemption amount {redeem_amt} exceeds remaining balance {balance}")

    new_balance = balance - redeem_amt
    new_status = "redeemed" if new_balance == 0 else "active"

    sql, params = dynamic_update("retailclaw_store_credit",
                                  {"remaining_balance": str(new_balance), "status": new_status},
                                  {"id": sc_id})
    conn.execute(sql, params)
    audit(conn, SKILL, "retail-redeem-store-credit",
          "retailclaw_store_credit", sc_id,
          new_values={"redeemed": str(redeem_amt), "remaining": str(new_balance)})
    conn.commit()
    ok({
        "store_credit_id": sc_id,
        "redeemed_amount": str(redeem_amt),
        "remaining_balance": str(new_balance),
        "status": new_status,
    })


def check_store_credit_balance(conn, args):
    customer_id = getattr(args, "customer_id", None)
    if not customer_id:
        err("--customer-id is required")

    rows = conn.execute(
        Q.from_(_t_credit).select(_t_credit.star)
        .where(_t_credit.customer_id == P())
        .where(_t_credit.status == P())
        .orderby(_t_credit.created_at, order=Order.desc)
        .get_sql(),
        (customer_id, "active"),
    ).fetchall()

    total_balance = Decimal("0")
    credits = []
    for r in rows:
        bal = _d(r["remaining_balance"])
        total_balance += bal
        credits.append(row_to_dict(r))

    ok({
        "customer_id": customer_id,
        "active_credits": len(credits),
        "total_balance": str(total_balance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "credits": credits,
    })


# ---------------------------------------------------------------------------
# ACTIONS registry
# ---------------------------------------------------------------------------
ACTIONS = {
    # R3: Retail Procurement
    "retail-check-reorder-points": check_reorder_points,
    "retail-generate-purchase-suggestions": generate_purchase_suggestions,
    "retail-auto-create-purchase-orders": auto_create_purchase_orders,
    "retail-procurement-report": procurement_report,
    # R4: Shift Scheduling
    "retail-add-store-shift": add_store_shift,
    "retail-list-store-schedules": list_store_schedules,
    # R5: Shrinkage/Loss Prevention
    "retail-record-shrinkage": record_shrinkage,
    "retail-list-shrinkage": list_shrinkage,
    "retail-shrinkage-report": shrinkage_report,
    "retail-shrinkage-by-cause-report": shrinkage_by_cause_report,
    # R6: Barcode Label Printing
    "retail-generate-barcode-labels": generate_barcode_labels,
    # R7: Customer Segmentation
    "retail-calculate-rfm": calculate_rfm,
    "retail-list-customer-segments": list_customer_segments,
    "retail-segment-performance-report": segment_performance_report,
    # R10: Store Credit
    "retail-issue-store-credit": issue_store_credit,
    "retail-redeem-store-credit": redeem_store_credit,
    "retail-check-store-credit-balance": check_store_credit_balance,
}
