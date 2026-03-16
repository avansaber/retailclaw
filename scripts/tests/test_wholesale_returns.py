"""Tests for RetailClaw wholesale and returns domains.

Actions tested (Wholesale):
  - retail-add-wholesale-customer
  - retail-update-wholesale-customer
  - retail-list-wholesale-customers
  - retail-add-wholesale-price
  - retail-list-wholesale-prices
  - retail-add-wholesale-order
  - retail-get-wholesale-order
  - retail-list-wholesale-orders
  - retail-add-wholesale-order-item
  - retail-list-wholesale-order-items

Actions tested (Returns):
  - retail-add-return-authorization
  - retail-update-return-authorization
  - retail-get-return-authorization
  - retail-list-return-authorizations
  - retail-add-return-item
  - retail-list-return-items
  - retail-process-return
  - retail-add-exchange
"""
import pytest
from decimal import Decimal
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ═══════════════════════════════════════════════════════════════════════════════
# WHOLESALE
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddWholesaleCustomer:
    def test_create_basic(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            business_name="Acme Distributors",
            contact_name="Bob Smith",
            email="bob@acme.com",
            phone="555-0199",
            tax_id="12-3456789",
            credit_limit="50000",
            payment_terms="Net 30",
            discount_pct="10",
            address_line1="123 Main St",
            address_line2="Suite 100",
            city="Springfield",
            state="IL",
            zip_code="62701",
        ))
        assert is_ok(result), result
        assert result["business_name"] == "Acme Distributors"
        assert result["wholesale_status"] == "active"

    def test_create_minimal(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name="Minimal Wholesale",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_ok(result), result

    def test_missing_business_name_fails(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name=None,
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=None,
            customer_id=None,
            business_name="No Company Inc",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_error(result)


class TestUpdateWholesaleCustomer:
    def _create_wc(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name="Update Target Inc",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_update_credit_limit(self, conn, env):
        wc_id = self._create_wc(conn, env)
        result = call_action(mod.retail_update_wholesale_customer, conn, ns(
            wholesale_customer_id=wc_id,
            business_name=None,
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit="75000",
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
            wholesale_status=None,
        ))
        assert is_ok(result), result
        assert "credit_limit" in result["updated_fields"]

    def test_update_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_wholesale_customer, conn, ns(
            wholesale_customer_id=None,
            business_name="Nope",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
            wholesale_status=None,
        ))
        assert is_error(result)


class TestListWholesaleCustomers:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_wholesale_customers, conn, ns(
            company_id=env["company_id"],
            wholesale_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_list_after_create(self, conn, env):
        call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name="WC One",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        result = call_action(mod.retail_list_wholesale_customers, conn, ns(
            company_id=env["company_id"],
            wholesale_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Wholesale Pricing
# ─────────────────────────────────────────────────────────────────────────────

class TestWholesalePricing:
    def _create_wc(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name="Pricing WC",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_wholesale_price(self, conn, env):
        wc_id = self._create_wc(conn, env)
        result = call_action(mod.retail_add_wholesale_price, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            item_id=env["item1"],
            item_name="Widget A",
            wholesale_rate="15.50",
            min_order_qty="10",
            currency="USD",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        ))
        assert is_ok(result), result
        assert result["wholesale_rate"] == "15.50"

    def test_add_wholesale_price_missing_rate_fails(self, conn, env):
        wc_id = self._create_wc(conn, env)
        result = call_action(mod.retail_add_wholesale_price, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            item_id=None,
            item_name=None,
            wholesale_rate=None,
            min_order_qty=None,
            currency=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)

    def test_list_wholesale_prices(self, conn, env):
        wc_id = self._create_wc(conn, env)
        call_action(mod.retail_add_wholesale_price, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            item_id=env["item1"],
            item_name="Widget A",
            wholesale_rate="15.50",
            min_order_qty=None,
            currency=None,
            valid_from=None,
            valid_to=None,
        ))
        result = call_action(mod.retail_list_wholesale_prices, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            item_id=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Wholesale Orders
# ─────────────────────────────────────────────────────────────────────────────

class TestWholesaleOrders:
    def _create_wc(self, conn, env):
        result = call_action(mod.retail_add_wholesale_customer, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            business_name="Order WC",
            contact_name=None,
            email=None,
            phone=None,
            tax_id=None,
            credit_limit=None,
            payment_terms=None,
            discount_pct=None,
            address_line1=None,
            address_line2=None,
            city=None,
            state=None,
            zip_code=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_wholesale_order(self, conn, env):
        wc_id = self._create_wc(conn, env)
        result = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date="2026-03-30",
            notes="Urgent order",
        ))
        assert is_ok(result), result
        assert result["order_status"] == "draft"
        assert "naming_series" in result

    def test_add_order_missing_customer_fails(self, conn, env):
        result = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=None,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_error(result)

    def test_add_order_missing_date_fails(self, conn, env):
        wc_id = self._create_wc(conn, env)
        result = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date=None,
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_error(result)

    def test_add_order_item_and_get(self, conn, env):
        wc_id = self._create_wc(conn, env)
        order = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_ok(order)
        oi = call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=order["id"],
            item_id=env["item1"],
            item_name="Widget A",
            qty="10",
            rate="25.00",
            notes=None,
        ))
        assert is_ok(oi), oi
        assert oi["qty"] == 10
        assert oi["rate"] == "25.00"
        assert oi["amount"] == "250.00"

        # Verify order totals updated
        get_result = call_action(mod.retail_get_wholesale_order, conn, ns(
            wholesale_order_id=order["id"],
        ))
        assert is_ok(get_result)
        assert Decimal(get_result["subtotal"]) == Decimal("250.00")
        assert get_result["item_count"] == 1

    def test_add_order_item_missing_name_fails(self, conn, env):
        wc_id = self._create_wc(conn, env)
        order = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_ok(order)
        result = call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=order["id"],
            item_id=None,
            item_name=None,
            qty="5",
            rate="10.00",
            notes=None,
        ))
        assert is_error(result)

    def test_add_order_item_missing_rate_fails(self, conn, env):
        wc_id = self._create_wc(conn, env)
        order = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_ok(order)
        result = call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=order["id"],
            item_id=None,
            item_name="Widget",
            qty="5",
            rate=None,
            notes=None,
        ))
        assert is_error(result)

    def test_list_wholesale_orders(self, conn, env):
        wc_id = self._create_wc(conn, env)
        call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        result = call_action(mod.retail_list_wholesale_orders, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=None,
            order_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1

    def test_list_wholesale_order_items(self, conn, env):
        wc_id = self._create_wc(conn, env)
        order = call_action(mod.retail_add_wholesale_order, conn, ns(
            company_id=env["company_id"],
            wholesale_customer_id=wc_id,
            order_date="2026-03-15",
            expected_delivery_date=None,
            notes=None,
        ))
        assert is_ok(order)
        call_action(mod.retail_add_wholesale_order_item, conn, ns(
            wholesale_order_id=order["id"],
            item_id=env["item1"],
            item_name="Widget A",
            qty="5",
            rate="20.00",
            notes=None,
        ))
        result = call_action(mod.retail_list_wholesale_order_items, conn, ns(
            wholesale_order_id=order["id"],
            item_id=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# RETURNS & EXCHANGES
# ═══════════════════════════════════════════════════════════════════════════════

class TestAddReturnAuthorization:
    def test_create_refund_return(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            customer_name="Return Customer",
            return_date="2026-03-10",
            reason="Defective product",
            return_type="refund",
            original_invoice_id=None,
            notes="Customer unhappy with quality",
        ))
        assert is_ok(result), result
        assert result["return_status"] == "pending"
        assert result["return_type"] == "refund"

    def test_create_exchange_return(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            customer_name="Exchange Customer",
            return_date="2026-03-11",
            reason="Wrong size",
            return_type="exchange",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(result), result
        assert result["return_type"] == "exchange"

    def test_missing_return_date_fails(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            customer_name="No Date",
            return_date=None,
            reason=None,
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=None,
            customer_id=None,
            customer_name="No Company",
            return_date="2026-03-10",
            reason=None,
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_error(result)

    def test_invalid_return_type_fails(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            customer_name="Bad Type",
            return_date="2026-03-10",
            reason=None,
            return_type="donation",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_error(result)


class TestReturnItems:
    def _create_return(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            customer_name="Item Return Customer",
            return_date="2026-03-10",
            reason="Not satisfied",
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_return_item(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=env["item1"],
            item_name="Widget A",
            qty="2",
            rate="29.99",
            reason="Damaged in shipping",
            item_condition="damaged",
            disposition="dispose",
        ))
        assert is_ok(result), result
        assert result["item_name"] == "Widget A"
        assert result["qty"] == 2
        assert Decimal(result["amount"]) == Decimal("59.98")

    def test_add_return_item_missing_name_fails(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=None,
            item_name=None,
            qty="1",
            rate="10.00",
            reason=None,
            item_condition=None,
            disposition=None,
        ))
        assert is_error(result)

    def test_add_return_item_missing_rate_fails(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=None,
            item_name="Widget",
            qty="1",
            rate=None,
            reason=None,
            item_condition=None,
            disposition=None,
        ))
        assert is_error(result)

    def test_add_return_item_missing_return_id_fails(self, conn, env):
        result = call_action(mod.retail_add_return_item, conn, ns(
            return_id=None,
            item_id=None,
            item_name="Widget",
            qty="1",
            rate="10.00",
            reason=None,
            item_condition=None,
            disposition=None,
        ))
        assert is_error(result)

    def test_list_return_items(self, conn, env):
        rid = self._create_return(conn, env)
        call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=env["item1"],
            item_name="Widget A",
            qty="1",
            rate="20.00",
            reason=None,
            item_condition=None,
            disposition=None,
        ))
        result = call_action(mod.retail_list_return_items, conn, ns(
            return_id=rid,
            item_id=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


class TestUpdateReturnAuthorization:
    def _create_return(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            customer_name="Update Return",
            return_date="2026-03-10",
            reason=None,
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_update_status(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_update_return_authorization, conn, ns(
            return_id=rid,
            customer_name=None,
            reason="Updated reason",
            original_invoice_id=None,
            notes=None,
            return_type=None,
            return_status="approved",
            restocking_fee=None,
        ))
        assert is_ok(result), result
        assert "reason" in result["updated_fields"]
        assert "return_status" in result["updated_fields"]

    def test_update_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_return_authorization, conn, ns(
            return_id=None,
            customer_name=None,
            reason="Nope",
            original_invoice_id=None,
            notes=None,
            return_type=None,
            return_status=None,
            restocking_fee=None,
        ))
        assert is_error(result)


class TestGetReturnAuthorization:
    def test_get_with_items(self, conn, env):
        create = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            customer_name="Get Return Customer",
            return_date="2026-03-10",
            reason="Test get",
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(create)
        rid = create["id"]

        call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=env["item1"],
            item_name="Widget A",
            qty="1",
            rate="50.00",
            reason=None,
            item_condition="good",
            disposition="restock",
        ))

        result = call_action(mod.retail_get_return_authorization, conn, ns(
            return_id=rid,
        ))
        assert is_ok(result), result
        assert result["item_count"] == 1
        assert len(result["items"]) == 1
        assert "exchanges" in result


class TestListReturnAuthorizations:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_return_authorizations, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            return_status=None,
            return_type=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 0


class TestProcessReturn:
    def _create_return_with_item(self, conn, env):
        ra = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            customer_name="Process Customer",
            return_date="2026-03-10",
            reason="Processing test",
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(ra)
        rid = ra["id"]

        call_action(mod.retail_add_return_item, conn, ns(
            return_id=rid,
            item_id=env["item1"],
            item_name="Widget A",
            qty="2",
            rate="30.00",
            reason=None,
            item_condition="good",
            disposition="restock",
        ))
        return rid

    def test_process_return_completed(self, conn, env):
        rid = self._create_return_with_item(conn, env)
        result = call_action(mod.retail_process_return, conn, ns(
            return_id=rid,
            return_status="completed",
            sales_returns_account_id=None,
            cash_account_id=None,
            inventory_account_id=None,
            cogs_account_id=None,
            cost_center_id=None,
            restock_cost=None,
        ))
        assert is_ok(result), result
        assert result["return_status"] == "completed"
        assert result["items_processed"] == 1
        assert Decimal(result["subtotal"]) == Decimal("60.00")

    def test_process_return_no_items_fails(self, conn, env):
        ra = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=None,
            customer_name="Empty Return",
            return_date="2026-03-10",
            reason=None,
            return_type="refund",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(ra)
        result = call_action(mod.retail_process_return, conn, ns(
            return_id=ra["id"],
            return_status="completed",
            sales_returns_account_id=None,
            cash_account_id=None,
            inventory_account_id=None,
            cogs_account_id=None,
            cost_center_id=None,
            restock_cost=None,
        ))
        assert is_error(result)

    def test_process_already_completed_fails(self, conn, env):
        rid = self._create_return_with_item(conn, env)
        # First process
        call_action(mod.retail_process_return, conn, ns(
            return_id=rid,
            return_status="completed",
            sales_returns_account_id=None,
            cash_account_id=None,
            inventory_account_id=None,
            cogs_account_id=None,
            cost_center_id=None,
            restock_cost=None,
        ))
        # Try to process again
        result = call_action(mod.retail_process_return, conn, ns(
            return_id=rid,
            return_status="completed",
            sales_returns_account_id=None,
            cash_account_id=None,
            inventory_account_id=None,
            cogs_account_id=None,
            cost_center_id=None,
            restock_cost=None,
        ))
        assert is_error(result)


class TestAddExchange:
    def _create_return(self, conn, env):
        result = call_action(mod.retail_add_return_authorization, conn, ns(
            company_id=env["company_id"],
            customer_id=env["customer_id"],
            customer_name="Exchange Customer",
            return_date="2026-03-10",
            reason="Wrong size",
            return_type="exchange",
            original_invoice_id=None,
            notes=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_exchange(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_add_exchange, conn, ns(
            company_id=env["company_id"],
            return_id=rid,
            original_item_id=env["item1"],
            original_item_name="Widget A (Small)",
            new_item_id=env["item2"],
            new_item_name="Widget B (Large)",
            qty="1",
            price_difference="5.00",
            notes="Size exchange",
        ))
        assert is_ok(result), result
        assert result["new_item_name"] == "Widget B (Large)"
        assert result["exchange_status"] == "pending"

    def test_add_exchange_missing_new_item_name_fails(self, conn, env):
        rid = self._create_return(conn, env)
        result = call_action(mod.retail_add_exchange, conn, ns(
            company_id=env["company_id"],
            return_id=rid,
            original_item_id=None,
            original_item_name=None,
            new_item_id=None,
            new_item_name=None,
            qty="1",
            price_difference=None,
            notes=None,
        ))
        assert is_error(result)

    def test_add_exchange_missing_return_id_fails(self, conn, env):
        result = call_action(mod.retail_add_exchange, conn, ns(
            company_id=env["company_id"],
            return_id=None,
            original_item_id=None,
            original_item_name=None,
            new_item_id=None,
            new_item_name="Widget B",
            qty="1",
            price_difference=None,
            notes=None,
        ))
        assert is_error(result)
