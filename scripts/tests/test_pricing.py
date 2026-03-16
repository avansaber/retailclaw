"""Tests for RetailClaw pricing domain.

Actions tested:
  - retail-add-price-list
  - retail-update-price-list
  - retail-get-price-list
  - retail-list-price-lists
  - retail-add-price-list-item
  - retail-update-price-list-item
  - retail-list-price-list-items
  - retail-add-promotion
  - retail-update-promotion
  - retail-list-promotions
  - retail-activate-promotion
  - retail-deactivate-promotion
"""
import pytest
from decimal import Decimal
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Price Lists
# ─────────────────────────────────────────────────────────────────────────────

class TestAddPriceList:
    def test_create_basic(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Standard Retail",
            description="Main retail price list",
            price_list_type="selling",
            currency="USD",
            is_default="1",
            valid_from="2026-01-01",
            valid_to="2026-12-31",
        ))
        assert is_ok(result), result
        assert result["name"] == "Standard Retail"
        assert result["price_list_status"] == "active"
        assert "id" in result
        assert "naming_series" in result

    def test_create_buying_type(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Purchase Prices",
            description=None,
            price_list_type="buying",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(result), result

    def test_missing_name_fails(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name=None,
            description=None,
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=None,
            name="Test PL",
            description=None,
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)

    def test_invalid_type_fails(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Bad PL",
            description=None,
            price_list_type="wholesale",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)


class TestUpdatePriceList:
    def _create(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Update Target",
            description="Initial",
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_update_name(self, conn, env):
        pl_id = self._create(conn, env)
        result = call_action(mod.retail_update_price_list, conn, ns(
            price_list_id=pl_id,
            name="Updated Name",
            description=None,
            currency=None,
            valid_from=None,
            valid_to=None,
            price_list_type=None,
            price_list_status=None,
        ))
        assert is_ok(result), result
        assert "name" in result["updated_fields"]

    def test_update_nonexistent_fails(self, conn, env):
        result = call_action(mod.retail_update_price_list, conn, ns(
            price_list_id="nonexistent-id",
            name="Nope",
            description=None,
            currency=None,
            valid_from=None,
            valid_to=None,
            price_list_type=None,
            price_list_status=None,
        ))
        assert is_error(result)

    def test_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_price_list, conn, ns(
            price_list_id=None,
            name="Nope",
            description=None,
            currency=None,
            valid_from=None,
            valid_to=None,
            price_list_type=None,
            price_list_status=None,
        ))
        assert is_error(result)


class TestGetPriceList:
    def test_get_existing(self, conn, env):
        create = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Lookup PL",
            description="For get test",
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_get_price_list, conn, ns(
            price_list_id=create["id"],
        ))
        assert is_ok(result), result
        assert result["name"] == "Lookup PL"
        assert result["item_count"] == 0

    def test_get_missing_fails(self, conn, env):
        result = call_action(mod.retail_get_price_list, conn, ns(
            price_list_id="no-such-id",
        ))
        assert is_error(result)


class TestListPriceLists:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_price_lists, conn, ns(
            company_id=env["company_id"],
            status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_list_after_create(self, conn, env):
        call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="PL1",
            description=None,
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="PL2",
            description=None,
            price_list_type="buying",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        result = call_action(mod.retail_list_price_lists, conn, ns(
            company_id=env["company_id"],
            status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Price List Items
# ─────────────────────────────────────────────────────────────────────────────

class TestPriceListItems:
    def _create_pl(self, conn, env):
        result = call_action(mod.retail_add_price_list, conn, ns(
            company_id=env["company_id"],
            name="Items PL",
            description=None,
            price_list_type="selling",
            currency="USD",
            is_default=None,
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_item_to_price_list(self, conn, env):
        pl_id = self._create_pl(conn, env)
        result = call_action(mod.retail_add_price_list_item, conn, ns(
            price_list_id=pl_id,
            item_id=env["item1"],
            item_name="Widget A",
            rate="29.99",
            min_qty="1",
            currency="USD",
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(result), result
        assert result["rate"] == "29.99"
        assert result["price_list_id"] == pl_id

    def test_add_item_missing_rate_fails(self, conn, env):
        pl_id = self._create_pl(conn, env)
        result = call_action(mod.retail_add_price_list_item, conn, ns(
            price_list_id=pl_id,
            item_id=env["item1"],
            item_name="Widget A",
            rate=None,
            min_qty="1",
            currency="USD",
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)

    def test_add_item_missing_pl_fails(self, conn, env):
        result = call_action(mod.retail_add_price_list_item, conn, ns(
            price_list_id=None,
            item_id=env["item1"],
            item_name="Widget A",
            rate="10.00",
            min_qty="1",
            currency="USD",
            valid_from=None,
            valid_to=None,
        ))
        assert is_error(result)

    def test_update_price_list_item(self, conn, env):
        pl_id = self._create_pl(conn, env)
        create = call_action(mod.retail_add_price_list_item, conn, ns(
            price_list_id=pl_id,
            item_id=env["item1"],
            item_name="Widget A",
            rate="29.99",
            min_qty="1",
            currency="USD",
            valid_from=None,
            valid_to=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_update_price_list_item, conn, ns(
            price_list_item_id=create["id"],
            item_name=None,
            currency=None,
            valid_from=None,
            valid_to=None,
            rate="39.99",
            min_qty=None,
        ))
        assert is_ok(result), result
        assert "rate" in result["updated_fields"]

    def test_list_price_list_items(self, conn, env):
        pl_id = self._create_pl(conn, env)
        call_action(mod.retail_add_price_list_item, conn, ns(
            price_list_id=pl_id,
            item_id=env["item1"],
            item_name="Widget A",
            rate="29.99",
            min_qty="1",
            currency="USD",
            valid_from=None,
            valid_to=None,
        ))
        result = call_action(mod.retail_list_price_list_items, conn, ns(
            price_list_id=pl_id,
            item_id=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Promotions
# ─────────────────────────────────────────────────────────────────────────────

class TestAddPromotion:
    def test_create_percentage_promo(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="Summer Sale",
            description="20% off everything",
            promo_type="percentage",
            discount_value="20",
            min_purchase="50",
            max_discount="100",
            max_uses="1000",
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-06-01",
            end_date="2026-08-31",
        ))
        assert is_ok(result), result
        assert result["promo_status"] == "draft"
        assert result["name"] == "Summer Sale"

    def test_create_bogo_promo(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="BOGO Weekdays",
            description=None,
            promo_type="bogo",
            discount_value="0",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-03-01",
            end_date="2026-03-31",
        ))
        assert is_ok(result), result

    def test_missing_name_fails(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name=None,
            description=None,
            promo_type="percentage",
            discount_value="10",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        ))
        assert is_error(result)

    def test_missing_promo_type_fails(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="No Type",
            description=None,
            promo_type=None,
            discount_value="10",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        ))
        assert is_error(result)

    def test_missing_dates_fails(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="No Dates",
            description=None,
            promo_type="fixed",
            discount_value="5",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date=None,
            end_date="2026-12-31",
        ))
        assert is_error(result)

    def test_invalid_promo_type_fails(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="Bad Type",
            description=None,
            promo_type="free_shipping",
            discount_value="10",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        ))
        assert is_error(result)


class TestPromotionLifecycle:
    def _create_promo(self, conn, env):
        result = call_action(mod.retail_add_promotion, conn, ns(
            company_id=env["company_id"],
            name="Lifecycle Promo",
            description=None,
            promo_type="percentage",
            discount_value="10",
            min_purchase=None,
            max_discount=None,
            max_uses=None,
            applicable_items=None,
            applicable_categories=None,
            start_date="2026-01-01",
            end_date="2026-12-31",
        ))
        assert is_ok(result)
        return result["id"]

    def test_activate_from_draft(self, conn, env):
        pid = self._create_promo(conn, env)
        result = call_action(mod.retail_activate_promotion, conn, ns(
            promotion_id=pid,
        ))
        assert is_ok(result), result
        assert result["promo_status"] == "active"

    def test_deactivate_active(self, conn, env):
        pid = self._create_promo(conn, env)
        # Activate first
        call_action(mod.retail_activate_promotion, conn, ns(promotion_id=pid))
        # Now deactivate
        result = call_action(mod.retail_deactivate_promotion, conn, ns(
            promotion_id=pid,
        ))
        assert is_ok(result), result
        assert result["promo_status"] == "paused"

    def test_deactivate_draft_fails(self, conn, env):
        pid = self._create_promo(conn, env)
        result = call_action(mod.retail_deactivate_promotion, conn, ns(
            promotion_id=pid,
        ))
        assert is_error(result)

    def test_activate_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_activate_promotion, conn, ns(
            promotion_id=None,
        ))
        assert is_error(result)

    def test_update_promotion(self, conn, env):
        pid = self._create_promo(conn, env)
        result = call_action(mod.retail_update_promotion, conn, ns(
            promotion_id=pid,
            name="Updated Promo",
            description=None,
            start_date=None,
            end_date=None,
            applicable_items=None,
            applicable_categories=None,
            promo_type=None,
            discount_value="25",
            min_purchase=None,
            max_uses=None,
        ))
        assert is_ok(result), result
        assert "discount_value" in result["updated_fields"]
        assert "name" in result["updated_fields"]

    def test_list_promotions(self, conn, env):
        self._create_promo(conn, env)
        result = call_action(mod.retail_list_promotions, conn, ns(
            company_id=env["company_id"],
            promo_status=None,
            promo_type=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1
