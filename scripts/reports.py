"""RetailClaw -- reports domain module

Analytics and reporting actions (7 actions, no dedicated tables -- reads from all domains).
Imported by db_query.py (unified router).
"""
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

try:
    sys.path.insert(0, os.path.expanduser("~/.openclaw/erpclaw/lib"))
    from erpclaw_lib.db import get_connection, DEFAULT_DB_PATH
    from erpclaw_lib.decimal_utils import to_decimal, round_currency
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, insert_row, update_row
except ImportError:
    DEFAULT_DB_PATH = "~/.openclaw/erpclaw/data.sqlite"
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# 1. channel-performance
# ===========================================================================
def channel_performance(conn, args):
    """Sales performance by price list (channel proxy)."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("pl.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "start_date", None):
        where.append("pl.created_at >= ?")
        params.append(args.start_date)
    if getattr(args, "end_date", None):
        where.append("pl.created_at <= ?")
        params.append(args.end_date)

    where_sql = " AND ".join(where)
    rows = conn.execute(f"""
        SELECT pl.name AS channel_name,
               pl.price_list_type,
               COUNT(pli.id) AS item_count,
               COALESCE(SUM(CAST(pli.rate AS REAL)), 0) AS total_value,
               pl.status
        FROM retailclaw_price_list pl
        LEFT JOIN retailclaw_price_list_item pli ON pli.price_list_id = pl.id
        WHERE {where_sql}
        GROUP BY pl.id, pl.name, pl.price_list_type, pl.status
        ORDER BY total_value DESC
    """, params).fetchall()

    results = []
    for r in rows:
        results.append({
            "channel_name": r[0],
            "price_list_type": r[1],
            "item_count": r[2],
            "total_value": str(round_currency(to_decimal(str(r[3])))),
            "channel_status": r[4],
        })

    ok({"report": "retail-channel-performance", "rows": results, "total_channels": len(results)})


# ===========================================================================
# 2. margin-analysis
# ===========================================================================
def margin_analysis(conn, args):
    """Margin analysis comparing wholesale vs retail pricing."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("pli.price_list_id IN (SELECT id FROM retailclaw_price_list WHERE company_id = ?)")
        params.append(args.company_id)

    where_sql = " AND ".join(where)
    rows = conn.execute(f"""
        SELECT pli.item_name,
               pli.rate AS retail_rate,
               COALESCE(wp.wholesale_rate, '0.00') AS wholesale_rate,
               pli.item_id
        FROM retailclaw_price_list_item pli
        LEFT JOIN retailclaw_wholesale_price wp ON wp.item_id = pli.item_id
        WHERE {where_sql} AND pli.item_name IS NOT NULL
        ORDER BY pli.item_name ASC
        LIMIT ? OFFSET ?
    """, params + [args.limit, args.offset]).fetchall()

    results = []
    for r in rows:
        retail = to_decimal(str(r[1]))
        wholesale = to_decimal(str(r[2]))
        margin = retail - wholesale if retail > Decimal("0") else Decimal("0")
        margin_pct = (margin / retail * Decimal("100")) if retail > Decimal("0") else Decimal("0")
        results.append({
            "item_name": r[0],
            "retail_rate": str(round_currency(retail)),
            "wholesale_rate": str(round_currency(wholesale)),
            "margin": str(round_currency(margin)),
            "margin_pct": str(round_currency(margin_pct)),
            "item_id": r[3],
        })

    ok({"report": "retail-margin-analysis", "rows": results, "total_items": len(results)})


# ===========================================================================
# 3. loyalty-report
# ===========================================================================
def loyalty_report(conn, args):
    """Loyalty program statistics: members, points issued/redeemed by tier."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("lm.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "program_id", None):
        where.append("lm.program_id = ?")
        params.append(args.program_id)

    where_sql = " AND ".join(where)

    # Member stats by tier
    tier_rows = conn.execute(f"""
        SELECT lm.member_tier,
               COUNT(*) AS member_count,
               SUM(lm.points_balance) AS total_points_balance,
               SUM(lm.lifetime_points) AS total_lifetime_points
        FROM retailclaw_loyalty_member lm
        WHERE {where_sql}
        GROUP BY lm.member_tier
        ORDER BY total_lifetime_points DESC
    """, params).fetchall()

    tiers = []
    total_members = 0
    total_balance = 0
    total_lifetime = 0
    for r in tier_rows:
        count = r[1]
        balance = r[2] or 0
        lifetime = r[3] or 0
        tiers.append({
            "tier": r[0],
            "member_count": count,
            "total_points_balance": balance,
            "total_lifetime_points": lifetime,
        })
        total_members += count
        total_balance += balance
        total_lifetime += lifetime

    # Transaction summary
    txn_rows = conn.execute("""
        SELECT lt.transaction_type, COUNT(*), SUM(ABS(lt.points))
        FROM retailclaw_loyalty_transaction lt
        JOIN retailclaw_loyalty_member lm ON lm.id = lt.member_id
        WHERE """ + where_sql + """
        GROUP BY lt.transaction_type
    """, params).fetchall()

    transactions = {}
    for r in txn_rows:
        transactions[r[0]] = {"count": r[1], "total_points": r[2] or 0}

    ok({
        "report": "retail-loyalty-report",
        "total_members": total_members,
        "total_points_balance": total_balance,
        "total_lifetime_points": total_lifetime,
        "tiers": tiers,
        "transactions": transactions,
    })


# ===========================================================================
# 4. category-performance
# ===========================================================================
def category_performance(conn, args):
    """Category listing with item counts from planograms."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("c.company_id = ?")
        params.append(args.company_id)

    where_sql = " AND ".join(where)
    rows = conn.execute(f"""
        SELECT c.id, c.name, c.parent_id, c.is_active,
               (SELECT COUNT(*) FROM retailclaw_category c2 WHERE c2.parent_id = c.id) AS subcategory_count
        FROM retailclaw_category c
        WHERE {where_sql}
        ORDER BY c.sort_order ASC, c.name ASC
        LIMIT ? OFFSET ?
    """, params + [args.limit, args.offset]).fetchall()

    results = []
    for r in rows:
        results.append({
            "category_id": r[0],
            "name": r[1],
            "parent_id": r[2],
            "is_active": r[3],
            "subcategory_count": r[4],
        })

    ok({"report": "retail-category-performance", "rows": results, "total_categories": len(results)})


# ===========================================================================
# 5. promotion-effectiveness
# ===========================================================================
def promotion_effectiveness(conn, args):
    """Promotion stats: usage rate, redemption counts."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("company_id = ?")
        params.append(args.company_id)
    if getattr(args, "promo_status", None):
        where.append("promo_status = ?")
        params.append(args.promo_status)

    where_sql = " AND ".join(where)
    rows = conn.execute(f"""
        SELECT id, name, promo_type, discount_value, max_uses, used_count,
               start_date, end_date, promo_status
        FROM retailclaw_promotion
        WHERE {where_sql}
        ORDER BY used_count DESC
        LIMIT ? OFFSET ?
    """, params + [args.limit, args.offset]).fetchall()

    results = []
    for r in rows:
        max_uses = r[4]
        used = r[5]
        utilization = (used / max_uses * 100) if max_uses and max_uses > 0 else None
        results.append({
            "promotion_id": r[0],
            "name": r[1],
            "promo_type": r[2],
            "discount_value": r[3],
            "max_uses": max_uses,
            "used_count": used,
            "utilization_pct": round(utilization, 2) if utilization is not None else None,
            "start_date": r[6],
            "end_date": r[7],
            "promo_status": r[8],
        })

    ok({"report": "retail-promotion-effectiveness", "rows": results, "total_promotions": len(results)})


# ===========================================================================
# 6. inventory-turnover
# ===========================================================================
def inventory_turnover(conn, args):
    """Wholesale order volume by item as a proxy for inventory turnover."""
    where, params = ["1=1"], []
    if getattr(args, "company_id", None):
        where.append("wo.company_id = ?")
        params.append(args.company_id)
    if getattr(args, "start_date", None):
        where.append("wo.order_date >= ?")
        params.append(args.start_date)
    if getattr(args, "end_date", None):
        where.append("wo.order_date <= ?")
        params.append(args.end_date)

    where_sql = " AND ".join(where)
    rows = conn.execute(f"""
        SELECT woi.item_name,
               SUM(woi.qty) AS total_qty,
               SUM(CAST(woi.amount AS REAL)) AS total_amount,
               COUNT(DISTINCT wo.id) AS order_count
        FROM retailclaw_wholesale_order_item woi
        JOIN retailclaw_wholesale_order wo ON wo.id = woi.order_id
        WHERE {where_sql} AND wo.order_status != 'cancelled'
        GROUP BY woi.item_name
        ORDER BY total_qty DESC
        LIMIT ? OFFSET ?
    """, params + [args.limit, args.offset]).fetchall()

    results = []
    for r in rows:
        results.append({
            "item_name": r[0],
            "total_qty": r[1],
            "total_amount": str(round_currency(to_decimal(str(r[2])))),
            "order_count": r[3],
        })

    ok({"report": "retail-inventory-turnover", "rows": results, "total_items": len(results)})


# ===========================================================================
# 7. status
# ===========================================================================
def status_action(conn, args):
    """RetailClaw module status."""
    table_counts = {}
    for table in [
        "retailclaw_price_list", "retailclaw_price_list_item",
        "retailclaw_promotion", "retailclaw_coupon",
        "retailclaw_loyalty_program", "retailclaw_loyalty_member",
        "retailclaw_loyalty_transaction", "retailclaw_gift_card",
        "retailclaw_category", "retailclaw_planogram",
        "retailclaw_planogram_item", "retailclaw_display",
        "retailclaw_wholesale_customer", "retailclaw_wholesale_price",
        "retailclaw_wholesale_order", "retailclaw_wholesale_order_item",
        "retailclaw_return_authorization", "retailclaw_return_item",
        "retailclaw_exchange",
    ]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            table_counts[table] = count
        except Exception:
            table_counts[table] = "missing"

    ok({
        "skill": "retailclaw",
        "version": "1.0.0",
        "tables": table_counts,
        "total_tables": len(table_counts),
        "database": DEFAULT_DB_PATH,
    })


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-channel-performance": channel_performance,
    "retail-margin-analysis": margin_analysis,
    "retail-loyalty-report": loyalty_report,
    "retail-category-performance": category_performance,
    "retail-promotion-effectiveness": promotion_effectiveness,
    "retail-inventory-turnover": inventory_turnover,
    "status": status_action,
}
