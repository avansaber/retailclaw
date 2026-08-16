#!/usr/bin/env python3
"""RetailClaw schema extension -- adds retail domain tables to the shared database.

AI-native retail management: pricing, promotions, loyalty programs, merchandising,
wholesale/B2B, returns & exchanges, multi-location, shrinkage, store credit.
21 tables across 8 domains, all prefixed with retailclaw_.

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]

ADR-0034 phase 2 bulk-39. Schema declared as metadata and provisioned through
`erpclaw_lib.seam`, which emits dialect-correct DDL, replacing a hand-written
``CREATE TABLE`` block opened with ``sqlite3.connect`` that could not run on
PostgreSQL at all. Conversion rules are the pilot's (`erpclaw-esign`): seam
vocabulary only, and every amount this vertical carries — price-list rates,
promotion and coupon discounts, gift-card balances, wholesale totals, refund and
restocking amounts, store credit — stays TEXT, which is the rule that matters
most in a module that prices and settles.

The pre-conversion docstring said "19 tables across 5 domains". It predated the
multi-location, shrinkage and store-credit domains and never subtracted the
retired `retailclaw_display`; the installer creates 21 across 8 and has since
that table was dropped — corrected here rather than carried.
"""
import importlib.util
import os
import sys

# Bootstrap the shared lib only when it is not already reachable — an
# unconditional insert at position 0 overrides a caller that deliberately bound a
# different tree (ADR-0034 phase 2 step 2d).
if importlib.util.find_spec("erpclaw_lib") is None:
    sys.path.insert(0, os.path.join(os.path.expanduser(
        os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "lib"))

from erpclaw_lib.seam import (  # noqa: E402
    CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, Table, Text,
    provision, reference_table, text,
)

DEFAULT_DB_PATH = os.path.join(os.path.expanduser(os.environ.get("ERPCLAW_HOME", "~/.openclaw/erpclaw")), "data.sqlite")
DISPLAY_NAME = "RetailClaw"

REQUIRED_FOUNDATION = [
    "company", "customer", "item", "naming_series", "audit_log",
]

METADATA = MetaData()

# Foundation tables this module points at but does not own. Declared for foreign
# key resolution only and never created here — see `seam.reference_table`.
reference_table("company", METADATA)
reference_table("customer", METADATA)
reference_table("item", METADATA)

# ==================================================================
# DOMAIN 1: PRICING (4 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 1. retailclaw_price_list
# ---------------------------------------------------------------------------
PRICE_LIST = Table(
    "retailclaw_price_list", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("currency", Text, nullable=False, server_default=text("'USD'")),
    Column("price_list_type", Text, nullable=False, server_default=text("'selling'")),
    Column("is_default", Integer, nullable=False, server_default=text("0")),
    Column("valid_from", Text),
    Column("valid_to", Text),
    Column("status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("price_list_type IN ('selling','buying','transfer')",
                    name="ck_retailclaw_price_list_price_list_type"),
    CheckConstraint("status IN ('active','inactive','archived')",
                    name="ck_retailclaw_price_list_status"),
)

Index("idx_rc_price_list_company", PRICE_LIST.c.company_id)
Index("idx_rc_price_list_status", PRICE_LIST.c.status)

# ---------------------------------------------------------------------------
# 2. retailclaw_price_list_item
# ---------------------------------------------------------------------------
PRICE_LIST_ITEM = Table(
    "retailclaw_price_list_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("price_list_id", Text,
           ForeignKey("retailclaw_price_list.id", ondelete="CASCADE"),
           nullable=False),
    Column("item_id", Text, ForeignKey("item.id")),
    Column("item_name", Text),
    Column("rate", Text, nullable=False, server_default=text("'0.00'")),
    Column("min_qty", Text, nullable=False, server_default=text("'1'")),
    Column("currency", Text, nullable=False, server_default=text("'USD'")),
    Column("valid_from", Text),
    Column("valid_to", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_rc_pli_price_list", PRICE_LIST_ITEM.c.price_list_id)
Index("idx_rc_pli_item", PRICE_LIST_ITEM.c.item_id)

# ---------------------------------------------------------------------------
# 3. retailclaw_promotion
# ---------------------------------------------------------------------------
PROMOTION = Table(
    "retailclaw_promotion", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("promo_type", Text, nullable=False),
    Column("discount_value", Text, nullable=False, server_default=text("'0.00'")),
    Column("min_purchase", Text, nullable=False, server_default=text("'0.00'")),
    Column("max_discount", Text),
    Column("max_uses", Integer),
    Column("used_count", Integer, nullable=False, server_default=text("0")),
    Column("applicable_items", Text),
    Column("applicable_categories", Text),
    Column("start_date", Text, nullable=False),
    Column("end_date", Text, nullable=False),
    Column("promo_status", Text, nullable=False, server_default=text("'draft'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "promo_type IN ('bogo','percentage','fixed','bundle','tiered')",
        name="ck_retailclaw_promotion_promo_type"),
    CheckConstraint(
        "promo_status IN ('draft','active','paused','expired','cancelled')",
        name="ck_retailclaw_promotion_promo_status"),
)

Index("idx_rc_promo_company", PROMOTION.c.company_id)
Index("idx_rc_promo_status", PROMOTION.c.promo_status)
Index("idx_rc_promo_dates", PROMOTION.c.start_date, PROMOTION.c.end_date)

# ---------------------------------------------------------------------------
# 4. retailclaw_coupon
# ---------------------------------------------------------------------------
COUPON = Table(
    "retailclaw_coupon", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("promotion_id", Text, ForeignKey("retailclaw_promotion.id")),
    # `code` is the redemption key: without the UNIQUE, the same coupon code
    # could be issued twice and honoured twice.
    Column("code", Text, nullable=False, unique=True),
    Column("description", Text),
    Column("discount_type", Text, nullable=False,
           server_default=text("'percentage'")),
    Column("discount_value", Text, nullable=False, server_default=text("'0.00'")),
    Column("min_purchase", Text, nullable=False, server_default=text("'0.00'")),
    Column("max_uses", Integer),
    Column("used_count", Integer, nullable=False, server_default=text("0")),
    Column("single_use", Integer, nullable=False, server_default=text("0")),
    Column("valid_from", Text, nullable=False),
    Column("valid_to", Text, nullable=False),
    Column("coupon_status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("discount_type IN ('percentage','fixed')",
                    name="ck_retailclaw_coupon_discount_type"),
    CheckConstraint("coupon_status IN ('active','used','expired','cancelled')",
                    name="ck_retailclaw_coupon_coupon_status"),
)

Index("idx_rc_coupon_code", COUPON.c.code)
Index("idx_rc_coupon_company", COUPON.c.company_id)
Index("idx_rc_coupon_promo", COUPON.c.promotion_id)

# ==================================================================
# DOMAIN 2: LOYALTY (4 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 5. retailclaw_loyalty_program
# ---------------------------------------------------------------------------
LOYALTY_PROGRAM = Table(
    "retailclaw_loyalty_program", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("points_per_dollar", Text, nullable=False, server_default=text("'1'")),
    Column("redemption_rate", Text, nullable=False, server_default=text("'0.01'")),
    Column("tiers", Text, nullable=False, server_default=text("'[]'")),
    Column("program_status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("program_status IN ('active','inactive','archived')",
                    name="ck_retailclaw_loyalty_program_program_status"),
)

Index("idx_rc_loyalty_prog_company", LOYALTY_PROGRAM.c.company_id)

# ---------------------------------------------------------------------------
# 6. retailclaw_loyalty_member
# ---------------------------------------------------------------------------
LOYALTY_MEMBER = Table(
    "retailclaw_loyalty_member", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("program_id", Text,
           ForeignKey("retailclaw_loyalty_program.id"), nullable=False),
    Column("customer_id", Text, ForeignKey("customer.id")),
    Column("customer_name", Text, nullable=False),
    Column("email", Text),
    Column("phone", Text),
    Column("member_tier", Text, nullable=False, server_default=text("'bronze'")),
    # Points are a count, not money — Integer here is the shipped type.
    Column("points_balance", Integer, nullable=False, server_default=text("0")),
    Column("lifetime_points", Integer, nullable=False, server_default=text("0")),
    Column("enrollment_date", Text, nullable=False),
    Column("last_activity_date", Text),
    Column("member_status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("member_tier IN ('bronze','silver','gold','platinum')",
                    name="ck_retailclaw_loyalty_member_member_tier"),
    CheckConstraint(
        "member_status IN ('active','inactive','suspended','cancelled')",
        name="ck_retailclaw_loyalty_member_member_status"),
)

Index("idx_rc_loyalty_member_program", LOYALTY_MEMBER.c.program_id)
Index("idx_rc_loyalty_member_customer", LOYALTY_MEMBER.c.customer_id)
Index("idx_rc_loyalty_member_company", LOYALTY_MEMBER.c.company_id)
Index("idx_rc_loyalty_member_email", LOYALTY_MEMBER.c.email)

# ---------------------------------------------------------------------------
# 7. retailclaw_loyalty_transaction
# ---------------------------------------------------------------------------
LOYALTY_TRANSACTION = Table(
    "retailclaw_loyalty_transaction", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("member_id", Text,
           ForeignKey("retailclaw_loyalty_member.id"), nullable=False),
    Column("transaction_type", Text, nullable=False),
    Column("points", Integer, nullable=False),
    Column("balance_after", Integer, nullable=False),
    Column("reference_type", Text),
    Column("reference_id", Text),
    Column("description", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "transaction_type IN ('earn','redeem','adjust','expire','bonus')",
        name="ck_retailclaw_loyalty_transaction_transaction_type"),
)

Index("idx_rc_loyalty_txn_member", LOYALTY_TRANSACTION.c.member_id)
Index("idx_rc_loyalty_txn_type", LOYALTY_TRANSACTION.c.transaction_type)

# ---------------------------------------------------------------------------
# 8. retailclaw_gift_card
# ---------------------------------------------------------------------------
GIFT_CARD = Table(
    "retailclaw_gift_card", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    # The card number is bearer money: two rows with the same number would be
    # two claims on one balance.
    Column("card_number", Text, nullable=False, unique=True),
    Column("initial_balance", Text, nullable=False, server_default=text("'0.00'")),
    Column("current_balance", Text, nullable=False, server_default=text("'0.00'")),
    Column("currency", Text, nullable=False, server_default=text("'USD'")),
    Column("purchaser_name", Text),
    Column("recipient_name", Text),
    Column("recipient_email", Text),
    Column("issue_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("card_status", Text, nullable=False, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("card_status IN ('active','redeemed','expired','cancelled')",
                    name="ck_retailclaw_gift_card_card_status"),
)

Index("idx_rc_gift_card_number", GIFT_CARD.c.card_number)
Index("idx_rc_gift_card_company", GIFT_CARD.c.company_id)
Index("idx_rc_gift_card_status", GIFT_CARD.c.card_status)

# ==================================================================
# DOMAIN 3: MERCHANDISING (3 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 9. retailclaw_category
# ---------------------------------------------------------------------------
CATEGORY = Table(
    "retailclaw_category", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("name", Text, nullable=False),
    # Self-referential: a category's parent is another category.
    Column("parent_id", Text, ForeignKey("retailclaw_category.id")),
    Column("description", Text),
    Column("sort_order", Integer, nullable=False, server_default=text("0")),
    Column("is_active", Integer, nullable=False, server_default=text("1")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_rc_category_parent", CATEGORY.c.parent_id)
Index("idx_rc_category_company", CATEGORY.c.company_id)

# ---------------------------------------------------------------------------
# 10. retailclaw_planogram
# ---------------------------------------------------------------------------
PLANOGRAM = Table(
    "retailclaw_planogram", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("store_section", Text),
    Column("fixture_type", Text),
    Column("shelf_count", Integer, nullable=False, server_default=text("1")),
    Column("width_inches", Text),
    Column("height_inches", Text),
    Column("planogram_status", Text, nullable=False, server_default=text("'draft'")),
    Column("effective_date", Text),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("planogram_status IN ('draft','active','archived')",
                    name="ck_retailclaw_planogram_planogram_status"),
)

Index("idx_rc_planogram_company", PLANOGRAM.c.company_id)
Index("idx_rc_planogram_status", PLANOGRAM.c.planogram_status)

# ---------------------------------------------------------------------------
# 11. retailclaw_planogram_item
# ---------------------------------------------------------------------------
PLANOGRAM_ITEM = Table(
    "retailclaw_planogram_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("planogram_id", Text,
           ForeignKey("retailclaw_planogram.id", ondelete="CASCADE"),
           nullable=False),
    Column("item_id", Text, ForeignKey("item.id")),
    Column("item_name", Text),
    Column("shelf_number", Integer, nullable=False, server_default=text("1")),
    Column("position", Integer, nullable=False, server_default=text("1")),
    Column("facings", Integer, nullable=False, server_default=text("1")),
    Column("min_stock", Integer, nullable=False, server_default=text("0")),
    Column("max_stock", Integer),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_rc_plano_item_planogram", PLANOGRAM_ITEM.c.planogram_id)
Index("idx_rc_plano_item_item", PLANOGRAM_ITEM.c.item_id)

# 12. retailclaw_display removed 2026-07-02 (M31 H2 / migration 001). Zero
# actions ever existed for it. Register shows writers and readers both empty.
# The merchandising story is carried by retailclaw_planogram plus
# retailclaw_planogram_item. Dropped from existing DBs by this module's
# migration 001.

# ==================================================================
# DOMAIN 4: WHOLESALE (4 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 13. retailclaw_wholesale_customer
# ---------------------------------------------------------------------------
WHOLESALE_CUSTOMER = Table(
    "retailclaw_wholesale_customer", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("customer_id", Text, ForeignKey("customer.id")),
    Column("business_name", Text, nullable=False),
    Column("contact_name", Text),
    Column("email", Text),
    Column("phone", Text),
    Column("tax_id", Text),
    Column("credit_limit", Text, nullable=False, server_default=text("'0.00'")),
    Column("payment_terms", Text, nullable=False, server_default=text("'Net 30'")),
    Column("discount_pct", Text, nullable=False, server_default=text("'0.00'")),
    Column("address_line1", Text),
    Column("address_line2", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip_code", Text),
    Column("wholesale_status", Text, nullable=False,
           server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "wholesale_status IN ('active','inactive','suspended','pending_approval')",
        name="ck_retailclaw_wholesale_customer_wholesale_status"),
)

Index("idx_rc_ws_customer_company", WHOLESALE_CUSTOMER.c.company_id)
Index("idx_rc_ws_customer_cust", WHOLESALE_CUSTOMER.c.customer_id)

# ---------------------------------------------------------------------------
# 14. retailclaw_wholesale_price
# ---------------------------------------------------------------------------
WHOLESALE_PRICE = Table(
    "retailclaw_wholesale_price", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("wholesale_customer_id", Text,
           ForeignKey("retailclaw_wholesale_customer.id")),
    Column("item_id", Text, ForeignKey("item.id")),
    Column("item_name", Text),
    Column("wholesale_rate", Text, nullable=False, server_default=text("'0.00'")),
    Column("min_order_qty", Integer, nullable=False, server_default=text("1")),
    Column("currency", Text, nullable=False, server_default=text("'USD'")),
    Column("valid_from", Text),
    Column("valid_to", Text),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_rc_ws_price_customer", WHOLESALE_PRICE.c.wholesale_customer_id)
Index("idx_rc_ws_price_item", WHOLESALE_PRICE.c.item_id)
Index("idx_rc_ws_price_company", WHOLESALE_PRICE.c.company_id)

# ---------------------------------------------------------------------------
# 15. retailclaw_wholesale_order
# ---------------------------------------------------------------------------
WHOLESALE_ORDER = Table(
    "retailclaw_wholesale_order", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("wholesale_customer_id", Text,
           ForeignKey("retailclaw_wholesale_customer.id"), nullable=False),
    Column("order_date", Text, nullable=False),
    Column("expected_delivery_date", Text),
    Column("subtotal", Text, nullable=False, server_default=text("'0.00'")),
    Column("discount_amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("tax_amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("total", Text, nullable=False, server_default=text("'0.00'")),
    Column("notes", Text),
    Column("order_status", Text, nullable=False, server_default=text("'draft'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "order_status IN ('draft','confirmed','processing','shipped','delivered','cancelled')",
        name="ck_retailclaw_wholesale_order_order_status"),
)

Index("idx_rc_ws_order_customer", WHOLESALE_ORDER.c.wholesale_customer_id)
Index("idx_rc_ws_order_company", WHOLESALE_ORDER.c.company_id)
Index("idx_rc_ws_order_status", WHOLESALE_ORDER.c.order_status)

# ---------------------------------------------------------------------------
# 16. retailclaw_wholesale_order_item
# ---------------------------------------------------------------------------
WHOLESALE_ORDER_ITEM = Table(
    "retailclaw_wholesale_order_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("order_id", Text,
           ForeignKey("retailclaw_wholesale_order.id", ondelete="CASCADE"),
           nullable=False),
    Column("item_id", Text, ForeignKey("item.id")),
    Column("item_name", Text, nullable=False),
    Column("qty", Integer, nullable=False, server_default=text("1")),
    Column("rate", Text, nullable=False, server_default=text("'0.00'")),
    Column("amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("notes", Text),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
)

Index("idx_rc_ws_oi_order", WHOLESALE_ORDER_ITEM.c.order_id)
Index("idx_rc_ws_oi_item", WHOLESALE_ORDER_ITEM.c.item_id)

# ==================================================================
# DOMAIN 5: RETURNS (3 tables)
# ==================================================================

# ---------------------------------------------------------------------------
# 17. retailclaw_return_authorization
# ---------------------------------------------------------------------------
RETURN_AUTHORIZATION = Table(
    "retailclaw_return_authorization", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("naming_series", Text),
    Column("customer_id", Text, ForeignKey("customer.id")),
    Column("customer_name", Text),
    Column("return_date", Text, nullable=False),
    Column("reason", Text),
    Column("return_type", Text, nullable=False, server_default=text("'refund'")),
    # No foreign key on the shipped column, and none added here: the original
    # invoice may live in any of several billing tables.
    Column("original_invoice_id", Text),
    Column("subtotal", Text, nullable=False, server_default=text("'0.00'")),
    Column("restocking_fee", Text, nullable=False, server_default=text("'0.00'")),
    Column("refund_amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("gl_entry_ids", Text),
    Column("notes", Text),
    Column("return_status", Text, nullable=False, server_default=text("'pending'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("return_type IN ('refund','exchange','store_credit')",
                    name="ck_retailclaw_return_authorization_return_type"),
    CheckConstraint(
        "return_status IN ('pending','approved','received','inspected','completed','rejected','cancelled')",
        name="ck_retailclaw_return_authorization_return_status"),
)

Index("idx_rc_return_auth_company", RETURN_AUTHORIZATION.c.company_id)
Index("idx_rc_return_auth_customer", RETURN_AUTHORIZATION.c.customer_id)
Index("idx_rc_return_auth_status", RETURN_AUTHORIZATION.c.return_status)

# ---------------------------------------------------------------------------
# 18. retailclaw_return_item
# ---------------------------------------------------------------------------
RETURN_ITEM = Table(
    "retailclaw_return_item", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("return_id", Text,
           ForeignKey("retailclaw_return_authorization.id", ondelete="CASCADE"),
           nullable=False),
    Column("item_id", Text, ForeignKey("item.id")),
    Column("item_name", Text, nullable=False),
    Column("qty", Integer, nullable=False, server_default=text("1")),
    Column("rate", Text, nullable=False, server_default=text("'0.00'")),
    Column("amount", Text, nullable=False, server_default=text("'0.00'")),
    Column("reason", Text),
    Column("item_condition", Text, nullable=False, server_default=text("'good'")),
    Column("disposition", Text, nullable=False, server_default=text("'restock'")),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "item_condition IN ('good','damaged','defective','opened','sealed')",
        name="ck_retailclaw_return_item_item_condition"),
    CheckConstraint(
        "disposition IN ('restock','dispose','vendor_return','refurbish')",
        name="ck_retailclaw_return_item_disposition"),
)

Index("idx_rc_return_item_return", RETURN_ITEM.c.return_id)
Index("idx_rc_return_item_item", RETURN_ITEM.c.item_id)

# ---------------------------------------------------------------------------
# 19. retailclaw_exchange
# ---------------------------------------------------------------------------
# Asymmetry preserved: `retailclaw_return_item.return_id` cascades on delete,
# this one does not. Transcribed as shipped.
EXCHANGE = Table(
    "retailclaw_exchange", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("return_id", Text,
           ForeignKey("retailclaw_return_authorization.id"), nullable=False),
    Column("original_item_id", Text, ForeignKey("item.id")),
    Column("original_item_name", Text),
    Column("new_item_id", Text, ForeignKey("item.id")),
    Column("new_item_name", Text, nullable=False),
    Column("qty", Integer, nullable=False, server_default=text("1")),
    Column("price_difference", Text, nullable=False, server_default=text("'0.00'")),
    Column("exchange_status", Text, nullable=False,
           server_default=text("'pending'")),
    Column("notes", Text),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("exchange_status IN ('pending','completed','cancelled')",
                    name="ck_retailclaw_exchange_exchange_status"),
)

Index("idx_rc_exchange_return", EXCHANGE.c.return_id)
Index("idx_rc_exchange_company", EXCHANGE.c.company_id)

# ==================================================================
# DOMAIN 6: MULTI-LOCATION (1 table)
# ==================================================================

# ---------------------------------------------------------------------------
# 20. retailclaw_store_location
# ---------------------------------------------------------------------------
# Two asymmetries against the tables above, both as shipped: `company_id` comes
# second rather than last, and the status/type/timestamp columns carry defaults
# without NOT NULL.
STORE_LOCATION = Table(
    "retailclaw_store_location", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("store_code", Text),
    Column("warehouse_id", Text),
    Column("address", Text),
    Column("city", Text),
    Column("state", Text),
    Column("zip", Text),
    Column("store_type", Text, server_default=text("'retail'")),
    Column("manager_name", Text),
    Column("phone", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("created_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    Column("updated_at", Text, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "store_type IN ('retail','warehouse','distribution_center','online')",
        name="ck_retailclaw_store_location_store_type"),
    CheckConstraint("status IN ('active','inactive','closed')",
                    name="ck_retailclaw_store_location_status"),
)

Index("idx_rc_store_loc_company", STORE_LOCATION.c.company_id)
Index("idx_rc_store_loc_status", STORE_LOCATION.c.status)
Index("idx_rc_store_loc_type", STORE_LOCATION.c.store_type)

# ==================================================================
# DOMAIN 7: SHRINKAGE / LOSS PREVENTION (1 table)
# ==================================================================

# ---------------------------------------------------------------------------
# 21. retailclaw_shrinkage
# ---------------------------------------------------------------------------
# `store_location_id` and `item_id` carry no foreign key here, unlike their
# namesakes elsewhere in this module. Preserved as shipped.
SHRINKAGE = Table(
    "retailclaw_shrinkage", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("store_location_id", Text),
    Column("item_id", Text),
    Column("quantity", Text, nullable=False),
    Column("cause", Text, nullable=False),
    Column("discovered_date", Text, nullable=False),
    Column("reported_by", Text),
    Column("value_lost", Text, server_default=text("'0'")),
    Column("notes", Text),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint(
        "cause IN ('theft','damage','spoilage','admin_error','vendor_fraud','unknown')",
        name="ck_retailclaw_shrinkage_cause"),
)

Index("idx_rc_shrinkage_company", SHRINKAGE.c.company_id)
Index("idx_rc_shrinkage_store", SHRINKAGE.c.store_location_id)
Index("idx_rc_shrinkage_cause", SHRINKAGE.c.cause)
Index("idx_rc_shrinkage_date", SHRINKAGE.c.discovered_date)

# ==================================================================
# DOMAIN 8: STORE CREDIT (1 table)
# ==================================================================

# ---------------------------------------------------------------------------
# 22. retailclaw_store_credit
# ---------------------------------------------------------------------------
# `customer_id` is NOT NULL but carries no foreign key, unlike the nullable
# `customer_id` columns elsewhere in this module which do. Preserved as shipped.
STORE_CREDIT = Table(
    "retailclaw_store_credit", METADATA,
    Column("id", Text, primary_key=True, nullable=True),
    Column("customer_id", Text, nullable=False),
    Column("original_amount", Text, nullable=False, server_default=text("'0'")),
    Column("remaining_balance", Text, nullable=False, server_default=text("'0'")),
    Column("issued_date", Text, nullable=False),
    Column("expiration_date", Text),
    Column("source", Text),
    Column("source_reference_id", Text),
    Column("status", Text, server_default=text("'active'")),
    Column("company_id", Text, ForeignKey("company.id"), nullable=False),
    Column("created_at", Text, nullable=False,
           server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("source IN ('return','promotion','adjustment','gift')",
                    name="ck_retailclaw_store_credit_source"),
    CheckConstraint("status IN ('active','redeemed','expired')",
                    name="ck_retailclaw_store_credit_status"),
)

Index("idx_rc_store_credit_company", STORE_CREDIT.c.company_id)
Index("idx_rc_store_credit_customer", STORE_CREDIT.c.customer_id)
Index("idx_rc_store_credit_status", STORE_CREDIT.c.status)


def _require_foundation(db_path):
    """The pre-conversion installer's foundation probe, asked through the seam.

    The original read ``sqlite_master`` directly, so the guard that exists to
    produce a friendly error was itself SQLite-only. ``seam.table_exists``
    answers on both backends (ADR-0034 bulk-39). The wording is this module's
    own, unchanged.
    """
    from erpclaw_lib import seam

    missing = [t for t in REQUIRED_FOUNDATION if not seam.table_exists(t, db_path)]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw-setup first: clawhub install erpclaw-setup")
        sys.exit(1)


def create_retailclaw_tables(db_path=None):
    """Create RetailClaw tables and indexes on whichever backend is configured.

    Same contract as before the ADR-0034 conversion: idempotent, and the returned
    counts are what was ACTUALLY created rather than what was declared.
    """
    db_path = db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    _require_foundation(db_path)
    result = provision(METADATA, db_path)
    return {
        "database": db_path,
        "tables": result["tables"],
        "indexes": result["indexes"],
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    result = create_retailclaw_tables(db)
    print(f"{DISPLAY_NAME} schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
