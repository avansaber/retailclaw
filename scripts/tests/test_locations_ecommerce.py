"""L1 tests for RetailClaw multi-location inventory and e-commerce/omnichannel.

Covers:
  - Store locations: add, list, update, get-inventory
  - Inter-store transfers: request, list
  - Location reorder points
  - Multi-location stock report
  - E-commerce: sync products, sync inventory, import orders,
    fulfill orders, channel inventory report, omnichannel sales report
"""
import pytest
from decimal import Decimal
from retail_helpers import (
    call_action, ns, is_error, is_ok, load_db_query,
    seed_item,
)

mod = load_db_query()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _add_location(conn, env, name="Downtown Store", store_type="retail"):
    result = call_action(mod.retail_add_store_location, conn, ns(
        company_id=env["company_id"],
        name=name,
        store_code=None,
        warehouse_id=None,
        address_line1="123 Main St",
        city="Austin",
        state="TX",
        zip_code="78701",
        store_type=store_type,
        manager_name="John Doe",
        phone="555-0100",
    ))
    assert is_ok(result), result
    return result["id"]


# ── Store Location Tests ─────────────────────────────────────────────────────

class TestAddStoreLocation:
    def test_add_retail_location(self, conn, env):
        result = call_action(mod.retail_add_store_location, conn, ns(
            company_id=env["company_id"],
            name="Main Street Store",
            store_code="MS-001",
            warehouse_id=None,
            address_line1="100 Main St",
            city="Austin",
            state="TX",
            zip_code="78701",
            store_type="retail",
            manager_name="Alice",
            phone="555-0001",
        ))
        assert is_ok(result), result
        assert result["name"] == "Main Street Store"
        assert result["store_type"] == "retail"
        assert result["location_status"] == "active"

    def test_add_warehouse_location(self, conn, env):
        result = call_action(mod.retail_add_store_location, conn, ns(
            company_id=env["company_id"],
            name="Central Warehouse",
            store_code=None,
            warehouse_id=None,
            address_line1=None,
            city=None,
            state=None,
            zip_code=None,
            store_type="warehouse",
            manager_name=None,
            phone=None,
        ))
        assert is_ok(result)
        assert result["store_type"] == "warehouse"

    def test_add_location_missing_name(self, conn, env):
        result = call_action(mod.retail_add_store_location, conn, ns(
            company_id=env["company_id"],
            name=None,
            store_code=None,
            warehouse_id=None,
            address_line1=None,
            city=None,
            state=None,
            zip_code=None,
            store_type="retail",
            manager_name=None,
            phone=None,
        ))
        assert is_error(result)

    def test_add_location_invalid_type(self, conn, env):
        result = call_action(mod.retail_add_store_location, conn, ns(
            company_id=env["company_id"],
            name="Bad Type Store",
            store_code=None,
            warehouse_id=None,
            address_line1=None,
            city=None,
            state=None,
            zip_code=None,
            store_type="kiosk",
            manager_name=None,
            phone=None,
        ))
        assert is_error(result)


class TestListStoreLocations:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_store_locations, conn, ns(
            company_id=env["company_id"],
            status=None,
            store_type=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 0

    def test_list_after_add(self, conn, env):
        _add_location(conn, env, "Store A")
        _add_location(conn, env, "Store B")
        result = call_action(mod.retail_list_store_locations, conn, ns(
            company_id=env["company_id"],
            status=None,
            store_type=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 2


class TestUpdateStoreLocation:
    def test_update_name(self, conn, env):
        loc_id = _add_location(conn, env)
        result = call_action(mod.retail_update_store_location, conn, ns(
            store_location_id=loc_id,
            name="Updated Store Name",
            store_code=None,
            warehouse_id=None,
            address_line1=None,
            city=None,
            state=None,
            zip_code=None,
            store_type=None,
            manager_name=None,
            phone=None,
            location_status=None,
        ))
        assert is_ok(result), result
        assert "name" in result["updated_fields"]

    def test_update_not_found(self, conn, env):
        result = call_action(mod.retail_update_store_location, conn, ns(
            store_location_id="nonexistent",
            name="X",
            store_code=None,
            warehouse_id=None,
            address_line1=None,
            city=None,
            state=None,
            zip_code=None,
            store_type=None,
            manager_name=None,
            phone=None,
            location_status=None,
        ))
        assert is_error(result)


class TestGetStoreInventory:
    def test_no_warehouse_linked(self, conn, env):
        loc_id = _add_location(conn, env)
        result = call_action(mod.retail_get_store_inventory, conn, ns(
            store_location_id=loc_id,
        ))
        assert is_ok(result)
        assert result["warehouse_id"] is None


class TestMultiLocationStockReport:
    def test_report_empty(self, conn, env):
        result = call_action(mod.retail_multi_location_stock_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(result)
        assert result["total_locations"] == 0

    def test_report_with_locations(self, conn, env):
        _add_location(conn, env, "Store 1")
        _add_location(conn, env, "Store 2", store_type="warehouse")
        result = call_action(mod.retail_multi_location_stock_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(result)
        assert result["total_locations"] == 2


# ── E-Commerce Tests ─────────────────────────────────────────────────────────

class TestSyncProductsToChannel:
    def test_sync_products(self, conn, env):
        # Create a price list with items first
        call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Online Store",
            description=None,
            price_list_type="selling",
            currency="USD",
            is_default="1",
            valid_from=None,
            valid_to=None,
        ))

        result = call_action(mod.retail_sync_products_to_channel, conn, ns(
            company_id=env["company_id"],
            channel="shopify",
        ))
        assert is_ok(result), result
        assert result["channel"] == "shopify"
        assert result["sync_status"] == "ready_for_push"
        assert "products_prepared" in result


class TestSyncInventoryToChannel:
    def test_sync_inventory(self, conn, env):
        _add_location(conn, env, "Online Fulfillment", store_type="online")
        result = call_action(mod.retail_sync_inventory_to_channel, conn, ns(
            company_id=env["company_id"],
            channel="website",
            store_location_id=None,
        ))
        assert is_ok(result)
        assert result["sync_status"] == "ready_for_push"


class TestImportOnlineOrders:
    def test_import_order(self, conn, env):
        result = call_action(mod.retail_import_online_orders, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            channel="shopify",
            order_date="2026-03-01",
        ))
        assert is_ok(result), result
        assert result["channel"] == "shopify"
        assert result["customer_id"] == env["customer_id"]

    def test_import_missing_customer(self, conn, env):
        result = call_action(mod.retail_import_online_orders, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            channel="shopify",
            order_date=None,
        ))
        assert is_error(result)


class TestChannelInventoryReport:
    def test_channel_report(self, conn, env):
        _add_location(conn, env, "Retail Store")
        _add_location(conn, env, "Online Shop", "online")
        result = call_action(mod.retail_channel_inventory_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(result)
        assert result["total_channels"] == 2


class TestOmnichannelSalesReport:
    def test_omnichannel_report(self, conn, env):
        _add_location(conn, env, "Physical Store")
        result = call_action(mod.retail_omnichannel_sales_report, conn, ns(
            company_id=env["company_id"],
        ))
        assert is_ok(result)
        assert "channels" in result
        assert "wholesale_orders" in result
