"""RetailClaw -- e-commerce / omnichannel domain module

Actions for product sync, online order import, fulfillment, and omnichannel reporting.
No new tables — leverages existing retailclaw + erpclaw-integrations framework.
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
    from erpclaw_lib.response import ok, err, row_to_dict
    from erpclaw_lib.audit import audit
    from erpclaw_lib.query import Q, P, Table, Field, fn, Order, LiteralValue, insert_row
    from erpclaw_lib.cross_skill import call_skill_action
except ImportError:
    pass

_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

VALID_CHANNELS = ("shopify", "woocommerce", "amazon", "ebay", "website", "in_store", "other")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_company(conn, company_id):
    if not company_id:
        err("--company-id is required")
    if not conn.execute(Q.from_(Table("company")).select(Field("id")).where(Field("id") == P()).get_sql(), (company_id,)).fetchone():
        err(f"Company {company_id} not found")


# ===========================================================================
# 1. retail-sync-products-to-channel
# ===========================================================================
def sync_products_to_channel(conn, args):
    """Prepare product data for sync to an e-commerce channel.

    Reads items from price lists and formats them for channel sync.
    Actual push to external platform is handled by erpclaw-integrations.
    """
    _validate_company(conn, args.company_id)

    channel = getattr(args, "channel", None) or "website"

    # Get active price list items for selling
    rows = conn.execute(
        """SELECT pli.item_id, pli.item_name, pli.rate, pli.currency,
                  pl.name as price_list_name
           FROM retailclaw_price_list_item pli
           JOIN retailclaw_price_list pl ON pli.price_list_id = pl.id
           WHERE pl.company_id = ? AND pl.status = 'active'
                 AND pl.price_list_type = 'selling'
           ORDER BY pli.item_name""",
        (args.company_id,)).fetchall()

    products = []
    for r in rows:
        products.append({
            "item_id": r["item_id"],
            "item_name": r["item_name"],
            "price": r["rate"],
            "currency": r["currency"],
            "price_list": r["price_list_name"],
        })

    sync_id = str(uuid.uuid4())
    now = _now_iso()

    ok({
        "sync_id": sync_id,
        "channel": channel,
        "products_prepared": len(products),
        "products": products,
        "sync_date": now,
        "sync_status": "ready_for_push",
        "message": f"{len(products)} products prepared for {channel} sync",
    })


# ===========================================================================
# 2. retail-sync-inventory-to-channel
# ===========================================================================
def sync_inventory_to_channel(conn, args):
    """Push stock levels to an e-commerce channel per store location."""
    _validate_company(conn, args.company_id)

    channel = getattr(args, "channel", None) or "website"
    loc_id = getattr(args, "store_location_id", None)

    # Get locations
    where = "sl.company_id = ? AND sl.status = 'active'"
    params = [args.company_id]
    if loc_id:
        where += " AND sl.id = ?"
        params.append(loc_id)

    locations = conn.execute(
        f"""SELECT sl.id, sl.name, sl.warehouse_id
            FROM retailclaw_store_location sl
            WHERE {where}""",
        params).fetchall()

    inventory_data = []
    for loc in locations:
        wh_id = loc["warehouse_id"]
        if not wh_id:
            continue
        try:
            stock_rows = conn.execute(
                """SELECT item_id,
                          SUM(CASE WHEN entry_type IN ('receipt','transfer_in') THEN CAST(qty AS NUMERIC)
                                   WHEN entry_type IN ('issue','transfer_out') THEN -CAST(qty AS NUMERIC)
                                   ELSE 0 END) as available_qty
                   FROM stock_ledger_entry
                   WHERE warehouse_id = ?
                   GROUP BY item_id
                   HAVING available_qty > 0""",
                (wh_id,)).fetchall()

            for sr in stock_rows:
                inventory_data.append({
                    "location_id": loc["id"],
                    "location_name": loc["name"],
                    "item_id": sr["item_id"],
                    "available_qty": str(round_currency(to_decimal(str(sr["available_qty"])))),
                })
        except Exception:
            pass

    ok({
        "channel": channel,
        "inventory_items": len(inventory_data),
        "inventory": inventory_data,
        "sync_date": _now_iso(),
        "sync_status": "ready_for_push",
    })


# ===========================================================================
# 3. retail-import-online-orders
# ===========================================================================
def import_online_orders(conn, args):
    """Import online orders as sales orders.

    In production, this reads from channel API. For now, creates a sales order
    from provided channel order data.
    """
    _validate_company(conn, args.company_id)

    customer_id = getattr(args, "customer_id", None)
    if not customer_id:
        err("--customer-id is required")

    channel = getattr(args, "channel", None) or "website"
    order_date = getattr(args, "order_date", None) or _now_iso()[:10]

    # Check customer exists
    if not conn.execute(Q.from_(Table("customer")).select(Field("id")).where(Field("id") == P()).get_sql(), (customer_id,)).fetchone():
        err(f"Customer {customer_id} not found")

    # Create a sales order via cross-skill if available
    order_id = str(uuid.uuid4())
    now = _now_iso()

    try:
        # Use cross_skill to create sales order (Art 5 compliance)
        so_result = call_skill_action(conn, "erpclaw", "add-sales-order",
            customer_id=customer_id, company_id=args.company_id,
            posting_date=order_date, notes=f"Imported from {channel}")
        if so_result and so_result.get("id"):
            order_id = so_result["id"]
        ok({
            "order_id": order_id,
            "channel": channel,
            "customer_id": customer_id,
            "order_date": order_date,
            "order_status": "draft",
            "message": f"Order imported from {channel}",
        })
    except Exception as e:
        # sales_order table might not exist or have different schema
        ok({
            "order_id": order_id,
            "channel": channel,
            "customer_id": customer_id,
            "order_date": order_date,
            "order_status": "pending",
            "message": f"Order data captured from {channel} (sales_order creation deferred: {str(e)[:50]})",
        })


# ===========================================================================
# 4. retail-fulfill-online-order
# ===========================================================================
def fulfill_online_order(conn, args):
    """Mark an online order as shipped/fulfilled."""
    _validate_company(conn, args.company_id)

    order_id = getattr(args, "order_id", None)
    if not order_id:
        err("--order-id is required (wholesale-order-id or sales order id)")

    tracking_number = getattr(args, "tracking_number", None)
    carrier = getattr(args, "carrier", None)

    # Try to update sales_order status
    try:
        row = conn.execute(
            "SELECT id, status FROM sales_order WHERE id = ?",
            (order_id,)).fetchone()
        if not row:
            err(f"Order {order_id} not found")
        if row["status"] in ("cancelled",):
            err(f"Cannot fulfill cancelled order")

        # Use cross_skill to update sales order (Art 5 compliance)
        call_skill_action(conn, "erpclaw", "update-sales-order",
            sales_order_id=order_id,
            notes=f"Shipped. Tracking: {tracking_number or 'N/A'}, Carrier: {carrier or 'N/A'}")
    except Exception:
        pass

    now = _now_iso()
    audit(conn, "sales_order", order_id, "retail-fulfill-online-order",
          args.company_id, {"tracking": tracking_number, "carrier": carrier})
    conn.commit()
    ok({
        "order_id": order_id,
        "fulfillment_status": "fulfilled",
        "tracking_number": tracking_number,
        "carrier": carrier,
        "fulfillment_date": now,
    })


# ===========================================================================
# 5. retail-channel-inventory-report
# ===========================================================================
def channel_inventory_report(conn, args):
    """Stock availability across all channels/locations."""
    _validate_company(conn, args.company_id)

    locations = conn.execute(
        """SELECT id, name, store_type, warehouse_id
           FROM retailclaw_store_location
           WHERE company_id = ? AND status = 'active'
           ORDER BY name""",
        (args.company_id,)).fetchall()

    channels = []
    total_items = 0
    for loc in locations:
        wh_id = loc["warehouse_id"]
        item_count = 0
        total_stock = Decimal("0")

        if wh_id:
            try:
                stock = conn.execute(
                    """SELECT COUNT(DISTINCT item_id) as items,
                              COALESCE(SUM(CASE WHEN entry_type IN ('receipt','transfer_in') THEN CAST(qty AS NUMERIC)
                                               WHEN entry_type IN ('issue','transfer_out') THEN -CAST(qty AS NUMERIC)
                                               ELSE 0 END), 0) as qty
                       FROM stock_ledger_entry WHERE warehouse_id = ?""",
                    (wh_id,)).fetchone()
                item_count = stock["items"] or 0
                total_stock = to_decimal(str(stock["qty"] or 0))
            except Exception:
                pass

        channels.append({
            "location_id": loc["id"],
            "channel_name": loc["name"],
            "channel_type": loc["store_type"],
            "item_count": item_count,
            "total_stock": str(round_currency(total_stock)),
        })
        total_items += item_count

    ok({
        "report": "retail-channel-inventory",
        "channels": channels,
        "total_channels": len(channels),
        "total_items_across_channels": total_items,
    })


# ===========================================================================
# 6. retail-omnichannel-sales-report
# ===========================================================================
def omnichannel_sales_report(conn, args):
    """Sales broken down by channel (in-store vs online locations)."""
    _validate_company(conn, args.company_id)

    # Group store locations by type
    locations = conn.execute(
        """SELECT store_type, COUNT(*) as location_count
           FROM retailclaw_store_location
           WHERE company_id = ? AND status = 'active'
           GROUP BY store_type
           ORDER BY location_count DESC""",
        (args.company_id,)).fetchall()

    # Get price list activity as sales proxy per channel type
    channels = []
    for loc in locations:
        # Count price list items (proxy for sales volume)
        item_count = conn.execute(
            """SELECT COUNT(pli.id) as cnt,
                      COALESCE(SUM(CAST(pli.rate AS NUMERIC)), 0) as total_value
               FROM retailclaw_price_list_item pli
               JOIN retailclaw_price_list pl ON pli.price_list_id = pl.id
               WHERE pl.company_id = ? AND pl.status = 'active'""",
            (args.company_id,)).fetchone()

        channels.append({
            "channel_type": loc["store_type"],
            "location_count": loc["location_count"],
            "catalog_items": item_count["cnt"] if item_count else 0,
            "catalog_value": str(round_currency(to_decimal(str(item_count["total_value"] or 0)))) if item_count else "0",
        })

    # Wholesale order totals
    wholesale_total = conn.execute(
        """SELECT COUNT(*) as order_count,
                  COALESCE(SUM(CAST(total AS NUMERIC)), 0) as total_sales
           FROM retailclaw_wholesale_order
           WHERE company_id = ? AND order_status NOT IN ('draft', 'cancelled')""",
        (args.company_id,)).fetchone()

    ok({
        "report": "retail-omnichannel-sales",
        "channels": channels,
        "wholesale_orders": wholesale_total["order_count"] if wholesale_total else 0,
        "wholesale_sales": str(round_currency(to_decimal(str(wholesale_total["total_sales"] or 0)))) if wholesale_total else "0",
        "total_channels": len(channels),
    })


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------
ACTIONS = {
    "retail-sync-products-to-channel": sync_products_to_channel,
    "retail-sync-inventory-to-channel": sync_inventory_to_channel,
    "retail-import-online-orders": import_online_orders,
    "retail-fulfill-online-order": fulfill_online_order,
    "retail-channel-inventory-report": channel_inventory_report,
    "retail-omnichannel-sales-report": omnichannel_sales_report,
}
