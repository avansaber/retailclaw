"""Tests for RetailClaw merchandising domain.

Actions tested:
  - retail-add-category
  - retail-update-category
  - retail-list-categories
  - retail-add-planogram
  - retail-update-planogram
  - retail-list-planograms
  - retail-add-planogram-item
  - retail-list-planogram-items
"""
import pytest
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Categories
# ─────────────────────────────────────────────────────────────────────────────

class TestAddCategory:
    def test_create_root_category(self, conn, env):
        result = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Electronics",
            parent_id=None,
            description="Consumer electronics",
            sort_order="1",
            is_active=None,
        ))
        assert is_ok(result), result
        assert result["name"] == "Electronics"
        assert result["parent_id"] is None
        assert "id" in result

    def test_create_subcategory(self, conn, env):
        parent = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Clothing",
            parent_id=None,
            description=None,
            sort_order=None,
            is_active=None,
        ))
        assert is_ok(parent)
        child = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Men's Shirts",
            parent_id=parent["id"],
            description="Dress and casual shirts",
            sort_order="1",
            is_active=None,
        ))
        assert is_ok(child), child
        assert child["parent_id"] == parent["id"]

    def test_missing_name_fails(self, conn, env):
        result = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name=None,
            parent_id=None,
            description=None,
            sort_order=None,
            is_active=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_category, conn, ns(
            company_id=None,
            name="Orphan",
            parent_id=None,
            description=None,
            sort_order=None,
            is_active=None,
        ))
        assert is_error(result)

    def test_nonexistent_parent_fails(self, conn, env):
        result = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Bad Child",
            parent_id="nonexistent-parent-id",
            description=None,
            sort_order=None,
            is_active=None,
        ))
        assert is_error(result)


class TestUpdateCategory:
    def _create_cat(self, conn, env, name="Update Target"):
        result = call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name=name,
            parent_id=None,
            description="Initial",
            sort_order="0",
            is_active=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_update_name(self, conn, env):
        cat_id = self._create_cat(conn, env)
        result = call_action(mod.retail_update_category, conn, ns(
            category_id=cat_id,
            name="Updated Category",
            description=None,
            sort_order=None,
            is_active=None,
            parent_id=None,
        ))
        assert is_ok(result), result
        assert "name" in result["updated_fields"]

    def test_update_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_category, conn, ns(
            category_id=None,
            name="Nope",
            description=None,
            sort_order=None,
            is_active=None,
            parent_id=None,
        ))
        assert is_error(result)

    def test_update_nonexistent_fails(self, conn, env):
        result = call_action(mod.retail_update_category, conn, ns(
            category_id="nonexistent-id",
            name="Nope",
            description=None,
            sort_order=None,
            is_active=None,
            parent_id=None,
        ))
        assert is_error(result)


class TestListCategories:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_categories, conn, ns(
            company_id=env["company_id"],
            parent_id=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_list_after_create(self, conn, env):
        call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Cat A",
            parent_id=None,
            description=None,
            sort_order="1",
            is_active=None,
        ))
        call_action(mod.retail_add_category, conn, ns(
            company_id=env["company_id"],
            name="Cat B",
            parent_id=None,
            description=None,
            sort_order="2",
            is_active=None,
        ))
        result = call_action(mod.retail_list_categories, conn, ns(
            company_id=env["company_id"],
            parent_id=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Planograms
# ─────────────────────────────────────────────────────────────────────────────

class TestAddPlanogram:
    def test_create_basic(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=env["company_id"],
            name="Aisle 3 Snacks",
            description="Snack foods display",
            store_section="Aisle 3",
            fixture_type="shelf",
            shelf_count="5",
            width_inches="48",
            height_inches="72",
            effective_date="2026-04-01",
        ))
        assert is_ok(result), result
        assert result["name"] == "Aisle 3 Snacks"
        assert result["planogram_status"] == "draft"

    def test_create_minimal(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=env["company_id"],
            name="Minimal Plano",
            description=None,
            store_section=None,
            fixture_type=None,
            shelf_count=None,
            width_inches=None,
            height_inches=None,
            effective_date=None,
        ))
        assert is_ok(result), result

    def test_missing_name_fails(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=env["company_id"],
            name=None,
            description=None,
            store_section=None,
            fixture_type=None,
            shelf_count=None,
            width_inches=None,
            height_inches=None,
            effective_date=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=None,
            name="No Company",
            description=None,
            store_section=None,
            fixture_type=None,
            shelf_count=None,
            width_inches=None,
            height_inches=None,
            effective_date=None,
        ))
        assert is_error(result)


class TestUpdatePlanogram:
    def _create_plano(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=env["company_id"],
            name="Update Plano",
            description=None,
            store_section=None,
            fixture_type=None,
            shelf_count=None,
            width_inches=None,
            height_inches=None,
            effective_date=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_update_section(self, conn, env):
        pid = self._create_plano(conn, env)
        result = call_action(mod.retail_update_planogram, conn, ns(
            planogram_id=pid,
            name=None,
            description=None,
            store_section="Front Entrance",
            fixture_type=None,
            effective_date=None,
            width_inches=None,
            height_inches=None,
            shelf_count=None,
            planogram_status=None,
        ))
        assert is_ok(result), result
        assert "store_section" in result["updated_fields"]

    def test_activate_planogram(self, conn, env):
        pid = self._create_plano(conn, env)
        result = call_action(mod.retail_update_planogram, conn, ns(
            planogram_id=pid,
            name=None,
            description=None,
            store_section=None,
            fixture_type=None,
            effective_date=None,
            width_inches=None,
            height_inches=None,
            shelf_count=None,
            planogram_status="active",
        ))
        assert is_ok(result), result
        assert "planogram_status" in result["updated_fields"]

    def test_update_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_planogram, conn, ns(
            planogram_id=None,
            name="Nope",
            description=None,
            store_section=None,
            fixture_type=None,
            effective_date=None,
            width_inches=None,
            height_inches=None,
            shelf_count=None,
            planogram_status=None,
        ))
        assert is_error(result)


class TestPlanogramItems:
    def _create_plano(self, conn, env):
        result = call_action(mod.retail_add_planogram, conn, ns(
            company_id=env["company_id"],
            name="Item Plano",
            description=None,
            store_section=None,
            fixture_type=None,
            shelf_count="4",
            width_inches=None,
            height_inches=None,
            effective_date=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_add_planogram_item(self, conn, env):
        pid = self._create_plano(conn, env)
        result = call_action(mod.retail_add_planogram_item, conn, ns(
            planogram_id=pid,
            item_id=env["item1"],
            item_name="Widget A",
            shelf_number="2",
            position="3",
            facings="4",
            min_stock="10",
            max_stock="50",
            notes="Eye level placement",
        ))
        assert is_ok(result), result
        assert result["planogram_id"] == pid
        assert result["item_name"] == "Widget A"

    def test_add_planogram_item_no_plano_fails(self, conn, env):
        result = call_action(mod.retail_add_planogram_item, conn, ns(
            planogram_id=None,
            item_id=None,
            item_name="Widget",
            shelf_number="1",
            position="1",
            facings="1",
            min_stock=None,
            max_stock=None,
            notes=None,
        ))
        assert is_error(result)

    def test_list_planogram_items(self, conn, env):
        pid = self._create_plano(conn, env)
        call_action(mod.retail_add_planogram_item, conn, ns(
            planogram_id=pid,
            item_id=env["item1"],
            item_name="Widget A",
            shelf_number="1",
            position="1",
            facings="2",
            min_stock=None,
            max_stock=None,
            notes=None,
        ))
        call_action(mod.retail_add_planogram_item, conn, ns(
            planogram_id=pid,
            item_id=env["item2"],
            item_name="Widget B",
            shelf_number="1",
            position="2",
            facings="3",
            min_stock=None,
            max_stock=None,
            notes=None,
        ))
        result = call_action(mod.retail_list_planogram_items, conn, ns(
            planogram_id=pid,
            item_id=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 2

    def test_list_planograms(self, conn, env):
        self._create_plano(conn, env)
        result = call_action(mod.retail_list_planograms, conn, ns(
            company_id=env["company_id"],
            planogram_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1
