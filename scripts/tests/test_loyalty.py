"""Tests for RetailClaw loyalty domain.

Actions tested:
  - retail-add-loyalty-program
  - retail-get-loyalty-program
  - retail-list-loyalty-programs
  - retail-add-loyalty-member
  - retail-update-loyalty-member
  - retail-get-loyalty-member
  - retail-list-loyalty-members
  - retail-add-loyalty-points
  - retail-redeem-loyalty-points
  - retail-add-gift-card
  - retail-check-gift-card-balance
  - retail-redeem-gift-card
"""
import pytest
from decimal import Decimal
from retail_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Loyalty Programs
# ─────────────────────────────────────────────────────────────────────────────

class TestAddLoyaltyProgram:
    def test_create_basic(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Rewards Plus",
            description="Customer loyalty program",
            points_per_dollar="2",
            redemption_rate="0.01",
            tiers=None,
        ))
        assert is_ok(result), result
        assert result["name"] == "Rewards Plus"
        assert result["program_status"] == "active"
        assert "id" in result

    def test_create_with_defaults(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Basic Rewards",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_ok(result), result
        assert result["program_status"] == "active"

    def test_missing_name_fails(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name=None,
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_error(result)

    def test_missing_company_fails(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=None,
            name="No Company",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_error(result)


class TestGetLoyaltyProgram:
    def _create_program(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Get Test Program",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_get_existing(self, conn, env):
        pid = self._create_program(conn, env)
        result = call_action(mod.retail_get_loyalty_program, conn, ns(
            program_id=pid,
        ))
        assert is_ok(result), result
        assert result["name"] == "Get Test Program"
        assert result["member_count"] == 0

    def test_get_missing_fails(self, conn, env):
        result = call_action(mod.retail_get_loyalty_program, conn, ns(
            program_id="nonexistent",
        ))
        assert is_error(result)

    def test_get_no_id_fails(self, conn, env):
        result = call_action(mod.retail_get_loyalty_program, conn, ns(
            program_id=None,
        ))
        assert is_error(result)


class TestListLoyaltyPrograms:
    def test_list_empty(self, conn, env):
        result = call_action(mod.retail_list_loyalty_programs, conn, ns(
            company_id=env["company_id"],
            program_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 0

    def test_list_with_filter(self, conn, env):
        call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Program A",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        result = call_action(mod.retail_list_loyalty_programs, conn, ns(
            company_id=env["company_id"],
            program_status="active",
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Loyalty Members
# ─────────────────────────────────────────────────────────────────────────────

class TestAddLoyaltyMember:
    def _create_program(self, conn, env):
        result = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Members Program",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_ok(result)
        return result["id"]

    def test_create_member(self, conn, env):
        pid = self._create_program(conn, env)
        result = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=pid,
            customer_id=env["customer_id"],
            customer_name="Jane Doe",
            email="jane@example.com",
            phone="555-0123",
            member_tier=None,
            enrollment_date="2026-01-15",
        ))
        assert is_ok(result), result
        assert result["customer_name"] == "Jane Doe"
        assert result["member_tier"] == "bronze"
        assert result["points_balance"] == 0

    def test_missing_program_fails(self, conn, env):
        result = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=None,
            customer_id=None,
            customer_name="Nobody",
            email=None,
            phone=None,
            member_tier=None,
            enrollment_date="2026-01-01",
        ))
        assert is_error(result)

    def test_missing_customer_name_fails(self, conn, env):
        pid = self._create_program(conn, env)
        result = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=pid,
            customer_id=None,
            customer_name=None,
            email=None,
            phone=None,
            member_tier=None,
            enrollment_date="2026-01-01",
        ))
        assert is_error(result)

    def test_missing_enrollment_date_fails(self, conn, env):
        pid = self._create_program(conn, env)
        result = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=pid,
            customer_id=None,
            customer_name="Test",
            email=None,
            phone=None,
            member_tier=None,
            enrollment_date=None,
        ))
        assert is_error(result)


class TestLoyaltyMemberOperations:
    def _setup_member(self, conn, env):
        prog = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Ops Program",
            description=None,
            points_per_dollar="1",
            redemption_rate="0.01",
            tiers=None,
        ))
        assert is_ok(prog)
        mem = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=prog["id"],
            customer_id=env["customer_id"],
            customer_name="Ops Member",
            email="ops@test.com",
            phone=None,
            member_tier=None,
            enrollment_date="2026-01-01",
        ))
        assert is_ok(mem)
        return prog["id"], mem["id"]

    def test_update_member_tier(self, conn, env):
        _, mid = self._setup_member(conn, env)
        result = call_action(mod.retail_update_loyalty_member, conn, ns(
            member_id=mid,
            customer_name=None,
            email=None,
            phone=None,
            member_tier="gold",
            member_status=None,
        ))
        assert is_ok(result), result
        assert "member_tier" in result["updated_fields"]

    def test_update_missing_id_fails(self, conn, env):
        result = call_action(mod.retail_update_loyalty_member, conn, ns(
            member_id=None,
            customer_name=None,
            email=None,
            phone=None,
            member_tier="gold",
            member_status=None,
        ))
        assert is_error(result)

    def test_get_member(self, conn, env):
        _, mid = self._setup_member(conn, env)
        result = call_action(mod.retail_get_loyalty_member, conn, ns(
            member_id=mid,
        ))
        assert is_ok(result), result
        assert result["customer_name"] == "Ops Member"
        assert "recent_transactions" in result

    def test_list_members(self, conn, env):
        _, _ = self._setup_member(conn, env)
        result = call_action(mod.retail_list_loyalty_members, conn, ns(
            company_id=env["company_id"],
            program_id=None,
            member_tier=None,
            member_status=None,
            search=None,
            limit=50,
            offset=0,
        ))
        assert is_ok(result)
        assert result["total_count"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Loyalty Points
# ─────────────────────────────────────────────────────────────────────────────

class TestLoyaltyPoints:
    def _setup_member(self, conn, env):
        prog = call_action(mod.retail_add_loyalty_program, conn, ns(
            company_id=env["company_id"],
            name="Points Program",
            description=None,
            points_per_dollar=None,
            redemption_rate=None,
            tiers=None,
        ))
        assert is_ok(prog)
        mem = call_action(mod.retail_add_loyalty_member, conn, ns(
            company_id=env["company_id"],
            program_id=prog["id"],
            customer_id=None,
            customer_name="Points Member",
            email=None,
            phone=None,
            member_tier=None,
            enrollment_date="2026-01-01",
        ))
        assert is_ok(mem)
        return mem["id"]

    def test_add_points(self, conn, env):
        mid = self._setup_member(conn, env)
        result = call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid,
            points=500,
            reference_type="sale",
            reference_id="INV-001",
            description="Purchase reward",
        ))
        assert is_ok(result), result
        assert result["points_added"] == 500
        assert result["points_balance"] == 500
        assert result["lifetime_points"] == 500

    def test_add_points_accumulate(self, conn, env):
        mid = self._setup_member(conn, env)
        call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid, points=200,
            reference_type=None, reference_id=None, description=None,
        ))
        result = call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid, points=300,
            reference_type=None, reference_id=None, description=None,
        ))
        assert is_ok(result)
        assert result["points_balance"] == 500
        assert result["lifetime_points"] == 500

    def test_add_zero_points_fails(self, conn, env):
        mid = self._setup_member(conn, env)
        result = call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid, points=0,
            reference_type=None, reference_id=None, description=None,
        ))
        assert is_error(result)

    def test_redeem_points(self, conn, env):
        mid = self._setup_member(conn, env)
        call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid, points=1000,
            reference_type=None, reference_id=None, description=None,
        ))
        result = call_action(mod.retail_redeem_loyalty_points, conn, ns(
            member_id=mid, points=400,
            reference_type="redemption", reference_id="RDM-001",
            description="In-store redemption",
        ))
        assert is_ok(result), result
        assert result["points_redeemed"] == 400
        assert result["points_balance"] == 600

    def test_redeem_insufficient_fails(self, conn, env):
        mid = self._setup_member(conn, env)
        call_action(mod.retail_add_loyalty_points, conn, ns(
            member_id=mid, points=100,
            reference_type=None, reference_id=None, description=None,
        ))
        result = call_action(mod.retail_redeem_loyalty_points, conn, ns(
            member_id=mid, points=500,
            reference_type=None, reference_id=None, description=None,
        ))
        assert is_error(result)

    def test_redeem_no_points_arg_fails(self, conn, env):
        mid = self._setup_member(conn, env)
        result = call_action(mod.retail_redeem_loyalty_points, conn, ns(
            member_id=mid, points=None,
            reference_type=None, reference_id=None, description=None,
        ))
        assert is_error(result)


# ─────────────────────────────────────────────────────────────────────────────
# Gift Cards
# ─────────────────────────────────────────────────────────────────────────────

class TestGiftCards:
    def test_add_gift_card(self, conn, env):
        result = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-TEST-001",
            initial_balance="100.00",
            currency="USD",
            purchaser_name="John Buyer",
            recipient_name="Jane Receiver",
            recipient_email="jane@example.com",
            issue_date="2026-03-01",
            expiration_date="2027-03-01",
        ))
        assert is_ok(result), result
        assert result["card_number"] == "GC-TEST-001"
        assert result["initial_balance"] == "100.00"
        assert result["card_status"] == "active"

    def test_add_gift_card_auto_number(self, conn, env):
        result = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number=None,
            initial_balance="50.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(result), result
        assert result["card_number"].startswith("GC-")

    def test_missing_balance_fails(self, conn, env):
        result = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number=None,
            initial_balance=None,
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_error(result)

    def test_missing_issue_date_fails(self, conn, env):
        result = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number=None,
            initial_balance="25.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date=None,
            expiration_date=None,
        ))
        assert is_error(result)

    def test_check_balance(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-BAL-001",
            initial_balance="75.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_check_gift_card_balance, conn, ns(
            card_number="GC-BAL-001",
            gift_card_id=None,
        ))
        assert is_ok(result), result
        assert result["current_balance"] == "75.00"
        assert result["card_status"] == "active"

    def test_check_balance_by_id(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-BYID-001",
            initial_balance="40.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_check_gift_card_balance, conn, ns(
            card_number=None,
            gift_card_id=create["id"],
        ))
        assert is_ok(result)
        assert result["current_balance"] == "40.00"

    def test_check_balance_no_identifier_fails(self, conn, env):
        result = call_action(mod.retail_check_gift_card_balance, conn, ns(
            card_number=None,
            gift_card_id=None,
        ))
        assert is_error(result)

    def test_redeem_gift_card(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-REDEEM-001",
            initial_balance="100.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_redeem_gift_card, conn, ns(
            card_number="GC-REDEEM-001",
            gift_card_id=None,
            amount="30.00",
        ))
        assert is_ok(result), result
        assert result["amount_redeemed"] == "30.00"
        assert result["current_balance"] == "70.00"
        assert result["card_status"] == "active"

    def test_redeem_full_balance(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-FULL-001",
            initial_balance="50.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_redeem_gift_card, conn, ns(
            card_number="GC-FULL-001",
            gift_card_id=None,
            amount="50.00",
        ))
        assert is_ok(result), result
        assert result["current_balance"] == "0.00"
        assert result["card_status"] == "redeemed"

    def test_redeem_insufficient_balance_fails(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-INSUF-001",
            initial_balance="20.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_redeem_gift_card, conn, ns(
            card_number="GC-INSUF-001",
            gift_card_id=None,
            amount="50.00",
        ))
        assert is_error(result)

    def test_redeem_no_amount_fails(self, conn, env):
        create = call_action(mod.retail_add_gift_card, conn, ns(
            company_id=env["company_id"],
            card_number="GC-NOAMT-001",
            initial_balance="20.00",
            currency=None,
            purchaser_name=None,
            recipient_name=None,
            recipient_email=None,
            issue_date="2026-03-01",
            expiration_date=None,
        ))
        assert is_ok(create)
        result = call_action(mod.retail_redeem_gift_card, conn, ns(
            card_number="GC-NOAMT-001",
            gift_card_id=None,
            amount=None,
        ))
        assert is_error(result)
