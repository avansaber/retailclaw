#!/usr/bin/env python3
"""RetailClaw schema extension -- adds retail domain tables to the shared database.

AI-native retail management: pricing, promotions, loyalty programs, merchandising,
wholesale/B2B, returns & exchanges.
19 tables across 5 domains, all prefixed with retailclaw_.

Prerequisite: ERPClaw init_db.py must have run first (creates foundation tables).
Run: python3 init_db.py [db_path]
"""
import os
import sqlite3
import sys

DEFAULT_DB_PATH = os.path.expanduser("~/.openclaw/erpclaw/data.sqlite")
DISPLAY_NAME = "RetailClaw"

REQUIRED_FOUNDATION = [
    "company", "customer", "item", "naming_series", "audit_log",
]


def create_retailclaw_tables(db_path=None):
    db_path = db_path or os.environ.get("ERPCLAW_DB_PATH", DEFAULT_DB_PATH)
    conn = sqlite3.connect(db_path)
    from erpclaw_lib.db import setup_pragmas
    setup_pragmas(conn)

    # -- Verify ERPClaw foundation --
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    missing = [t for t in REQUIRED_FOUNDATION if t not in tables]
    if missing:
        print(f"ERROR: Foundation tables missing: {', '.join(missing)}")
        print("Run erpclaw-setup first: clawhub install erpclaw-setup")
        conn.close()
        sys.exit(1)

    tables_created = 0
    indexes_created = 0

    # ==================================================================
    # DOMAIN 1: PRICING (4 tables)
    # ==================================================================

    # 1. retailclaw_price_list
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_price_list (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            name            TEXT NOT NULL,
            description     TEXT,
            currency        TEXT NOT NULL DEFAULT 'USD',
            price_list_type TEXT NOT NULL DEFAULT 'selling'
                            CHECK(price_list_type IN ('selling','buying','transfer')),
            is_default      INTEGER NOT NULL DEFAULT 0,
            valid_from      TEXT,
            valid_to        TEXT,
            status          TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active','inactive','archived')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_price_list_company ON retailclaw_price_list(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_price_list_status ON retailclaw_price_list(status)")
    indexes_created += 2

    # 2. retailclaw_price_list_item
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_price_list_item (
            id              TEXT PRIMARY KEY,
            price_list_id   TEXT NOT NULL REFERENCES retailclaw_price_list(id) ON DELETE CASCADE,
            item_id         TEXT REFERENCES item(id),
            item_name       TEXT,
            rate            TEXT NOT NULL DEFAULT '0.00',
            min_qty         TEXT NOT NULL DEFAULT '1',
            currency        TEXT NOT NULL DEFAULT 'USD',
            valid_from      TEXT,
            valid_to        TEXT,
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_pli_price_list ON retailclaw_price_list_item(price_list_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_pli_item ON retailclaw_price_list_item(item_id)")
    indexes_created += 2

    # 3. retailclaw_promotion
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_promotion (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            name            TEXT NOT NULL,
            description     TEXT,
            promo_type      TEXT NOT NULL
                            CHECK(promo_type IN ('bogo','percentage','fixed','bundle','tiered')),
            discount_value  TEXT NOT NULL DEFAULT '0.00',
            min_purchase    TEXT NOT NULL DEFAULT '0.00',
            max_discount    TEXT,
            max_uses        INTEGER,
            used_count      INTEGER NOT NULL DEFAULT 0,
            applicable_items TEXT,
            applicable_categories TEXT,
            start_date      TEXT NOT NULL,
            end_date        TEXT NOT NULL,
            promo_status    TEXT NOT NULL DEFAULT 'draft'
                            CHECK(promo_status IN ('draft','active','paused','expired','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_promo_company ON retailclaw_promotion(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_promo_status ON retailclaw_promotion(promo_status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_promo_dates ON retailclaw_promotion(start_date, end_date)")
    indexes_created += 3

    # 4. retailclaw_coupon
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_coupon (
            id              TEXT PRIMARY KEY,
            promotion_id    TEXT REFERENCES retailclaw_promotion(id),
            code            TEXT NOT NULL UNIQUE,
            description     TEXT,
            discount_type   TEXT NOT NULL DEFAULT 'percentage'
                            CHECK(discount_type IN ('percentage','fixed')),
            discount_value  TEXT NOT NULL DEFAULT '0.00',
            min_purchase    TEXT NOT NULL DEFAULT '0.00',
            max_uses        INTEGER,
            used_count      INTEGER NOT NULL DEFAULT 0,
            single_use      INTEGER NOT NULL DEFAULT 0,
            valid_from      TEXT NOT NULL,
            valid_to        TEXT NOT NULL,
            coupon_status   TEXT NOT NULL DEFAULT 'active'
                            CHECK(coupon_status IN ('active','used','expired','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_coupon_code ON retailclaw_coupon(code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_coupon_company ON retailclaw_coupon(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_coupon_promo ON retailclaw_coupon(promotion_id)")
    indexes_created += 3

    # ==================================================================
    # DOMAIN 2: LOYALTY (4 tables)
    # ==================================================================

    # 5. retailclaw_loyalty_program
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_loyalty_program (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            name            TEXT NOT NULL,
            description     TEXT,
            points_per_dollar TEXT NOT NULL DEFAULT '1',
            redemption_rate TEXT NOT NULL DEFAULT '0.01',
            tiers           TEXT NOT NULL DEFAULT '[]',
            program_status  TEXT NOT NULL DEFAULT 'active'
                            CHECK(program_status IN ('active','inactive','archived')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_prog_company ON retailclaw_loyalty_program(company_id)")
    indexes_created += 1

    # 6. retailclaw_loyalty_member
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_loyalty_member (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            program_id      TEXT NOT NULL REFERENCES retailclaw_loyalty_program(id),
            customer_id     TEXT REFERENCES customer(id),
            customer_name   TEXT NOT NULL,
            email           TEXT,
            phone           TEXT,
            member_tier     TEXT NOT NULL DEFAULT 'bronze'
                            CHECK(member_tier IN ('bronze','silver','gold','platinum')),
            points_balance  INTEGER NOT NULL DEFAULT 0,
            lifetime_points INTEGER NOT NULL DEFAULT 0,
            enrollment_date TEXT NOT NULL,
            last_activity_date TEXT,
            member_status   TEXT NOT NULL DEFAULT 'active'
                            CHECK(member_status IN ('active','inactive','suspended','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_member_program ON retailclaw_loyalty_member(program_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_member_customer ON retailclaw_loyalty_member(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_member_company ON retailclaw_loyalty_member(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_member_email ON retailclaw_loyalty_member(email)")
    indexes_created += 4

    # 7. retailclaw_loyalty_transaction
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_loyalty_transaction (
            id              TEXT PRIMARY KEY,
            member_id       TEXT NOT NULL REFERENCES retailclaw_loyalty_member(id),
            transaction_type TEXT NOT NULL
                            CHECK(transaction_type IN ('earn','redeem','adjust','expire','bonus')),
            points          INTEGER NOT NULL,
            balance_after   INTEGER NOT NULL,
            reference_type  TEXT,
            reference_id    TEXT,
            description     TEXT,
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_txn_member ON retailclaw_loyalty_transaction(member_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_loyalty_txn_type ON retailclaw_loyalty_transaction(transaction_type)")
    indexes_created += 2

    # 8. retailclaw_gift_card
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_gift_card (
            id              TEXT PRIMARY KEY,
            card_number     TEXT NOT NULL UNIQUE,
            initial_balance TEXT NOT NULL DEFAULT '0.00',
            current_balance TEXT NOT NULL DEFAULT '0.00',
            currency        TEXT NOT NULL DEFAULT 'USD',
            purchaser_name  TEXT,
            recipient_name  TEXT,
            recipient_email TEXT,
            issue_date      TEXT NOT NULL,
            expiration_date TEXT,
            card_status     TEXT NOT NULL DEFAULT 'active'
                            CHECK(card_status IN ('active','redeemed','expired','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_gift_card_number ON retailclaw_gift_card(card_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_gift_card_company ON retailclaw_gift_card(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_gift_card_status ON retailclaw_gift_card(card_status)")
    indexes_created += 3

    # ==================================================================
    # DOMAIN 3: MERCHANDISING (4 tables)
    # ==================================================================

    # 9. retailclaw_category
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_category (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            parent_id       TEXT REFERENCES retailclaw_category(id),
            description     TEXT,
            sort_order      INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_category_parent ON retailclaw_category(parent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_category_company ON retailclaw_category(company_id)")
    indexes_created += 2

    # 10. retailclaw_planogram
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_planogram (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            name            TEXT NOT NULL,
            description     TEXT,
            store_section   TEXT,
            fixture_type    TEXT,
            shelf_count     INTEGER NOT NULL DEFAULT 1,
            width_inches    TEXT,
            height_inches   TEXT,
            planogram_status TEXT NOT NULL DEFAULT 'draft'
                            CHECK(planogram_status IN ('draft','active','archived')),
            effective_date  TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_planogram_company ON retailclaw_planogram(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_planogram_status ON retailclaw_planogram(planogram_status)")
    indexes_created += 2

    # 11. retailclaw_planogram_item
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_planogram_item (
            id              TEXT PRIMARY KEY,
            planogram_id    TEXT NOT NULL REFERENCES retailclaw_planogram(id) ON DELETE CASCADE,
            item_id         TEXT REFERENCES item(id),
            item_name       TEXT,
            shelf_number    INTEGER NOT NULL DEFAULT 1,
            position        INTEGER NOT NULL DEFAULT 1,
            facings         INTEGER NOT NULL DEFAULT 1,
            min_stock       INTEGER NOT NULL DEFAULT 0,
            max_stock       INTEGER,
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_plano_item_planogram ON retailclaw_planogram_item(planogram_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_plano_item_item ON retailclaw_planogram_item(item_id)")
    indexes_created += 2

    # 12. retailclaw_display
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_display (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            display_type    TEXT NOT NULL DEFAULT 'endcap'
                            CHECK(display_type IN ('endcap','island','window','counter','pegboard','shelf','floor','wall')),
            location        TEXT,
            description     TEXT,
            start_date      TEXT,
            end_date        TEXT,
            promotion_id    TEXT REFERENCES retailclaw_promotion(id),
            display_status  TEXT NOT NULL DEFAULT 'planned'
                            CHECK(display_status IN ('planned','active','inactive','archived')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_display_company ON retailclaw_display(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_display_promo ON retailclaw_display(promotion_id)")
    indexes_created += 2

    # ==================================================================
    # DOMAIN 4: WHOLESALE (4 tables)
    # ==================================================================

    # 13. retailclaw_wholesale_customer
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_wholesale_customer (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            customer_id     TEXT REFERENCES customer(id),
            business_name   TEXT NOT NULL,
            contact_name    TEXT,
            email           TEXT,
            phone           TEXT,
            tax_id          TEXT,
            credit_limit    TEXT NOT NULL DEFAULT '0.00',
            payment_terms   TEXT NOT NULL DEFAULT 'Net 30',
            discount_pct    TEXT NOT NULL DEFAULT '0.00',
            address_line1   TEXT,
            address_line2   TEXT,
            city            TEXT,
            state           TEXT,
            zip_code        TEXT,
            wholesale_status TEXT NOT NULL DEFAULT 'active'
                            CHECK(wholesale_status IN ('active','inactive','suspended','pending_approval')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_customer_company ON retailclaw_wholesale_customer(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_customer_cust ON retailclaw_wholesale_customer(customer_id)")
    indexes_created += 2

    # 14. retailclaw_wholesale_price
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_wholesale_price (
            id              TEXT PRIMARY KEY,
            wholesale_customer_id TEXT REFERENCES retailclaw_wholesale_customer(id),
            item_id         TEXT REFERENCES item(id),
            item_name       TEXT,
            wholesale_rate  TEXT NOT NULL DEFAULT '0.00',
            min_order_qty   INTEGER NOT NULL DEFAULT 1,
            currency        TEXT NOT NULL DEFAULT 'USD',
            valid_from      TEXT,
            valid_to        TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_price_customer ON retailclaw_wholesale_price(wholesale_customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_price_item ON retailclaw_wholesale_price(item_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_price_company ON retailclaw_wholesale_price(company_id)")
    indexes_created += 3

    # 15. retailclaw_wholesale_order
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_wholesale_order (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            wholesale_customer_id TEXT NOT NULL REFERENCES retailclaw_wholesale_customer(id),
            order_date      TEXT NOT NULL,
            expected_delivery_date TEXT,
            subtotal        TEXT NOT NULL DEFAULT '0.00',
            discount_amount TEXT NOT NULL DEFAULT '0.00',
            tax_amount      TEXT NOT NULL DEFAULT '0.00',
            total           TEXT NOT NULL DEFAULT '0.00',
            notes           TEXT,
            order_status    TEXT NOT NULL DEFAULT 'draft'
                            CHECK(order_status IN ('draft','confirmed','processing','shipped','delivered','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_order_customer ON retailclaw_wholesale_order(wholesale_customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_order_company ON retailclaw_wholesale_order(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_order_status ON retailclaw_wholesale_order(order_status)")
    indexes_created += 3

    # 16. retailclaw_wholesale_order_item
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_wholesale_order_item (
            id              TEXT PRIMARY KEY,
            order_id        TEXT NOT NULL REFERENCES retailclaw_wholesale_order(id) ON DELETE CASCADE,
            item_id         TEXT REFERENCES item(id),
            item_name       TEXT NOT NULL,
            qty             INTEGER NOT NULL DEFAULT 1,
            rate            TEXT NOT NULL DEFAULT '0.00',
            amount          TEXT NOT NULL DEFAULT '0.00',
            notes           TEXT,
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_oi_order ON retailclaw_wholesale_order_item(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_ws_oi_item ON retailclaw_wholesale_order_item(item_id)")
    indexes_created += 2

    # ==================================================================
    # DOMAIN 5: RETURNS (3 tables)
    # ==================================================================

    # 17. retailclaw_return_authorization
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_return_authorization (
            id              TEXT PRIMARY KEY,
            naming_series   TEXT,
            customer_id     TEXT REFERENCES customer(id),
            customer_name   TEXT,
            return_date     TEXT NOT NULL,
            reason          TEXT,
            return_type     TEXT NOT NULL DEFAULT 'refund'
                            CHECK(return_type IN ('refund','exchange','store_credit')),
            original_invoice_id TEXT,
            subtotal        TEXT NOT NULL DEFAULT '0.00',
            restocking_fee  TEXT NOT NULL DEFAULT '0.00',
            refund_amount   TEXT NOT NULL DEFAULT '0.00',
            gl_entry_ids    TEXT,
            notes           TEXT,
            return_status   TEXT NOT NULL DEFAULT 'pending'
                            CHECK(return_status IN ('pending','approved','received','inspected','completed','rejected','cancelled')),
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_return_auth_company ON retailclaw_return_authorization(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_return_auth_customer ON retailclaw_return_authorization(customer_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_return_auth_status ON retailclaw_return_authorization(return_status)")
    indexes_created += 3

    # 18. retailclaw_return_item
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_return_item (
            id              TEXT PRIMARY KEY,
            return_id       TEXT NOT NULL REFERENCES retailclaw_return_authorization(id) ON DELETE CASCADE,
            item_id         TEXT REFERENCES item(id),
            item_name       TEXT NOT NULL,
            qty             INTEGER NOT NULL DEFAULT 1,
            rate            TEXT NOT NULL DEFAULT '0.00',
            amount          TEXT NOT NULL DEFAULT '0.00',
            reason          TEXT,
            item_condition  TEXT NOT NULL DEFAULT 'good'
                            CHECK(item_condition IN ('good','damaged','defective','opened','sealed')),
            disposition     TEXT NOT NULL DEFAULT 'restock'
                            CHECK(disposition IN ('restock','dispose','vendor_return','refurbish')),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_return_item_return ON retailclaw_return_item(return_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_return_item_item ON retailclaw_return_item(item_id)")
    indexes_created += 2

    # 19. retailclaw_exchange
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_exchange (
            id              TEXT PRIMARY KEY,
            return_id       TEXT NOT NULL REFERENCES retailclaw_return_authorization(id),
            original_item_id TEXT REFERENCES item(id),
            original_item_name TEXT,
            new_item_id     TEXT REFERENCES item(id),
            new_item_name   TEXT NOT NULL,
            qty             INTEGER NOT NULL DEFAULT 1,
            price_difference TEXT NOT NULL DEFAULT '0.00',
            exchange_status TEXT NOT NULL DEFAULT 'pending'
                            CHECK(exchange_status IN ('pending','completed','cancelled')),
            notes           TEXT,
            company_id      TEXT NOT NULL REFERENCES company(id),
            created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_exchange_return ON retailclaw_exchange(return_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_exchange_company ON retailclaw_exchange(company_id)")
    indexes_created += 2

    # ==================================================================
    # DOMAIN 6: MULTI-LOCATION (1 table)
    # ==================================================================

    # 20. retailclaw_store_location
    conn.execute("""
        CREATE TABLE IF NOT EXISTS retailclaw_store_location (
            id              TEXT PRIMARY KEY,
            company_id      TEXT NOT NULL REFERENCES company(id),
            name            TEXT NOT NULL,
            store_code      TEXT,
            warehouse_id    TEXT,
            address         TEXT,
            city            TEXT,
            state           TEXT,
            zip             TEXT,
            store_type      TEXT DEFAULT 'retail'
                            CHECK (store_type IN ('retail','warehouse','distribution_center','online')),
            manager_name    TEXT,
            phone           TEXT,
            status          TEXT DEFAULT 'active'
                            CHECK (status IN ('active','inactive','closed')),
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created += 1
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_store_loc_company ON retailclaw_store_location(company_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_store_loc_status ON retailclaw_store_location(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rc_store_loc_type ON retailclaw_store_location(store_type)")
    indexes_created += 3

    conn.commit()
    conn.close()

    return {
        "database": db_path,
        "tables": tables_created,
        "indexes": indexes_created,
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else None
    result = create_retailclaw_tables(db)
    print(f"{DISPLAY_NAME} schema created in {result['database']}")
    print(f"  Tables: {result['tables']}")
    print(f"  Indexes: {result['indexes']}")
