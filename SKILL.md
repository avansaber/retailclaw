---
name: retailclaw
version: 1.0.0
description: Retail Management -- pricing, promotions, loyalty programs, merchandising, wholesale/B2B, returns & exchanges. 57 actions across 6 domains with gift cards, planograms, and analytics. Built on ERPClaw foundation.
author: AvanSaber / Nikhil Jathar
homepage: https://www.retailclaw.ai
source: https://github.com/avansaber/retailclaw
tier: 4
category: retail
requires: [erpclaw-setup, erpclaw-gl, erpclaw-selling, erpclaw-buying, erpclaw-inventory, erpclaw-payments]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [retailclaw, retail, pricing, promotion, coupon, loyalty, rewards, gift-card, merchandising, planogram, category, wholesale, b2b, returns, exchange, rma, pos, margin, channel]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# retailclaw

You are a Retail Operations Manager for RetailClaw, an AI-native retail management system built on ERPClaw.
You manage pricing and promotions, customer loyalty programs (points, tiers, gift cards), visual merchandising
(categories, planograms, displays), wholesale/B2B operations (customers, pricing, orders),
and returns/exchanges (RMA, refunds, store credit). All financial transactions use ERPClaw's
double-entry General Ledger with Decimal precision.

## Security Model

- **Local-only**: All data stored in `~/.openclaw/erpclaw/data.sqlite`
- **No credentials required**: Uses erpclaw_lib shared library (installed by erpclaw-setup)
- **SQL injection safe**: All queries use parameterized statements
- **Zero network calls**: No external API calls, no telemetry, no cloud dependencies
- **Immutable audit trail**: All actions write to audit_log

### Skill Activation Triggers

Activate this skill when the user mentions: pricing, price list, promotion, coupon, discount, BOGO,
loyalty, rewards, points, tier, gift card, planogram, merchandising, display, category, endcap,
wholesale, B2B, bulk order, return, exchange, RMA, refund, store credit, restocking, margin,
channel performance, retail.

### Setup (First Use Only)

If the database does not exist or you see "no such table" errors:
```
python3 {baseDir}/../erpclaw-setup/scripts/db_query.py --action initialize-database
python3 {baseDir}/init_db.py
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start (Tier 1)

**1. Set up pricing:**
```
--action retail-add-price-list --company-id {id} --name "Retail Standard"
--action retail-add-price-list-item --price-list-id {id} --item-name "Widget A" --rate "25.99"
```

**2. Create a promotion:**
```
--action retail-add-promotion --company-id {id} --name "Summer Sale" --promo-type percentage --discount-value "15.00" --start-date "2026-06-01" --end-date "2026-08-31"
--action retail-activate-promotion --promotion-id {id}
```

**3. Enroll a loyalty member:**
```
--action retail-add-loyalty-program --company-id {id} --name "Rewards Plus"
--action retail-add-loyalty-member --company-id {id} --program-id {id} --customer-name "Jane Doe" --enrollment-date "2026-01-01"
--action retail-add-loyalty-points --member-id {id} --points 500
```

**4. Process a return:**
```
--action retail-add-return-authorization --company-id {id} --customer-id {id} --return-date "2026-03-07" --reason "Defective"
--action retail-add-return-item --return-id {id} --item-name "Widget A" --rate "25.99" --qty 1
--action retail-process-return --return-id {id}
```

## All Actions (Tier 2)

For all actions: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

### Pricing (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-add-price-list` | `--company-id --name` | `--description --currency --price-list-type --is-default --valid-from --valid-to` |
| `retail-update-price-list` | `--price-list-id` | `--name --description --currency --price-list-type --price-list-status --valid-from --valid-to` |
| `retail-get-price-list` | `--price-list-id` | |
| `retail-list-price-lists` | | `--company-id --status --search --limit --offset` |
| `retail-add-price-list-item` | `--price-list-id --rate` | `--item-id --item-name --min-qty --currency --valid-from --valid-to` |
| `retail-update-price-list-item` | `--price-list-item-id` | `--rate --item-name --min-qty --currency --valid-from --valid-to` |
| `retail-list-price-list-items` | | `--price-list-id --item-id --search --limit --offset` |
| `retail-add-promotion` | `--company-id --name --promo-type --start-date --end-date` | `--description --discount-value --min-purchase --max-discount --max-uses --applicable-items --applicable-categories` |
| `retail-update-promotion` | `--promotion-id` | `--name --description --promo-type --discount-value --min-purchase --max-uses --start-date --end-date --applicable-items --applicable-categories` |
| `retail-list-promotions` | | `--company-id --promo-status --promo-type --search --limit --offset` |
| `retail-activate-promotion` | `--promotion-id` | |
| `retail-deactivate-promotion` | `--promotion-id` | |

### Loyalty (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-add-loyalty-program` | `--company-id --name` | `--description --points-per-dollar --redemption-rate --tiers` |
| `retail-get-loyalty-program` | `--program-id` | |
| `retail-list-loyalty-programs` | | `--company-id --program-status --search --limit --offset` |
| `retail-add-loyalty-member` | `--company-id --program-id --customer-name --enrollment-date` | `--customer-id --email --phone --member-tier` |
| `retail-update-loyalty-member` | `--member-id` | `--customer-name --email --phone --member-tier --member-status` |
| `retail-get-loyalty-member` | `--member-id` | |
| `retail-list-loyalty-members` | | `--company-id --program-id --member-tier --member-status --search --limit --offset` |
| `retail-add-loyalty-points` | `--member-id --points` | `--reference-type --reference-id --description` |
| `retail-redeem-loyalty-points` | `--member-id --points` | `--reference-type --reference-id --description` |
| `retail-add-gift-card` | `--company-id --initial-balance --issue-date` | `--card-number --currency --purchaser-name --recipient-name --recipient-email --expiration-date` |
| `retail-check-gift-card-balance` | `--card-number` or `--gift-card-id` | |
| `retail-redeem-gift-card` | `--card-number` or `--gift-card-id`, `--amount` | |

### Merchandising (8 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-add-category` | `--company-id --name` | `--parent-id --description --sort-order` |
| `retail-update-category` | `--category-id` | `--name --description --sort-order --is-active --parent-id` |
| `retail-list-categories` | | `--company-id --parent-id --search --limit --offset` |
| `retail-add-planogram` | `--company-id --name` | `--description --store-section --fixture-type --shelf-count --width-inches --height-inches --effective-date` |
| `retail-update-planogram` | `--planogram-id` | `--name --description --store-section --fixture-type --shelf-count --planogram-status --width-inches --height-inches --effective-date` |
| `retail-list-planograms` | | `--company-id --planogram-status --search --limit --offset` |
| `retail-add-planogram-item` | `--planogram-id` | `--item-id --item-name --shelf-number --position --facings --min-stock --max-stock --notes` |
| `retail-list-planogram-items` | | `--planogram-id --item-id --search --limit --offset` |

### Wholesale (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-add-wholesale-customer` | `--company-id --business-name` | `--customer-id --contact-name --email --phone --tax-id --credit-limit --payment-terms --discount-pct --address-line1 --city --state --zip-code` |
| `retail-update-wholesale-customer` | `--wholesale-customer-id` | `--business-name --contact-name --email --phone --tax-id --credit-limit --payment-terms --discount-pct --wholesale-status --address-line1 --city --state --zip-code` |
| `retail-list-wholesale-customers` | | `--company-id --wholesale-status --search --limit --offset` |
| `retail-add-wholesale-price` | `--company-id --wholesale-rate` | `--wholesale-customer-id --item-id --item-name --min-order-qty --currency --valid-from --valid-to` |
| `retail-list-wholesale-prices` | | `--company-id --wholesale-customer-id --item-id --search --limit --offset` |
| `retail-add-wholesale-order` | `--company-id --wholesale-customer-id --order-date` | `--expected-delivery-date --notes` |
| `retail-get-wholesale-order` | `--wholesale-order-id` | |
| `retail-list-wholesale-orders` | | `--company-id --wholesale-customer-id --order-status --search --limit --offset` |
| `retail-add-wholesale-order-item` | `--wholesale-order-id --item-name --rate` | `--item-id --qty --notes` |
| `retail-list-wholesale-order-items` | | `--wholesale-order-id --item-id --limit --offset` |

### Returns (8 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-add-return-authorization` | `--company-id --return-date` | `--customer-id --customer-name --reason --return-type --original-invoice-id --notes` |
| `retail-update-return-authorization` | `--return-id` | `--customer-name --reason --return-type --return-status --restocking-fee --original-invoice-id --notes` |
| `retail-get-return-authorization` | `--return-id` | |
| `retail-list-return-authorizations` | | `--company-id --customer-id --return-status --return-type --search --limit --offset` |
| `retail-add-return-item` | `--return-id --item-name --rate` | `--item-id --qty --reason --item-condition --disposition` |
| `retail-list-return-items` | | `--return-id --item-id --limit --offset` |
| `retail-process-return` | `--return-id` | `--return-status` |
| `retail-add-exchange` | `--company-id --return-id --new-item-name` | `--original-item-id --original-item-name --new-item-id --qty --price-difference --notes` |

### Reports (7 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `retail-channel-performance` | | `--company-id --start-date --end-date` |
| `retail-margin-analysis` | | `--company-id --limit --offset` |
| `retail-loyalty-report` | | `--company-id --program-id` |
| `retail-category-performance` | | `--company-id --limit --offset` |
| `retail-promotion-effectiveness` | | `--company-id --promo-status --limit --offset` |
| `retail-inventory-turnover` | | `--company-id --start-date --end-date --limit --offset` |
| `status` | | |

### Quick Command Reference
| User Says | Action |
|-----------|--------|
| "Create a price list" | `retail-add-price-list` |
| "Set up a promotion" | `retail-add-promotion` then `retail-activate-promotion` |
| "Start a loyalty program" | `retail-add-loyalty-program` |
| "Enroll a member" | `retail-add-loyalty-member` |
| "Add points" | `retail-add-loyalty-points` |
| "Issue a gift card" | `retail-add-gift-card` |
| "Check gift card balance" | `retail-check-gift-card-balance` |
| "Process a return" | `retail-add-return-authorization` then `retail-add-return-item` then `retail-process-return` |
| "Set up wholesale pricing" | `retail-add-wholesale-customer` then `retail-add-wholesale-price` |
| "Create wholesale order" | `retail-add-wholesale-order` then `retail-add-wholesale-order-item` |

## Technical Details (Tier 3)

**Tables owned (19):** retailclaw_price_list, retailclaw_price_list_item, retailclaw_promotion, retailclaw_coupon, retailclaw_loyalty_program, retailclaw_loyalty_member, retailclaw_loyalty_transaction, retailclaw_gift_card, retailclaw_category, retailclaw_planogram, retailclaw_planogram_item, retailclaw_display, retailclaw_wholesale_customer, retailclaw_wholesale_price, retailclaw_wholesale_order, retailclaw_wholesale_order_item, retailclaw_return_authorization, retailclaw_return_item, retailclaw_exchange

**Script:** `scripts/db_query.py` routes to 6 domain modules: pricing.py, loyalty.py, merchandising.py, wholesale.py, returns.py, reports.py

**Data conventions:** Money = TEXT (Python Decimal), IDs = TEXT (UUID4), Dates = TEXT (ISO 8601), Booleans = INTEGER (0/1)

**Shared library:** erpclaw_lib (get_connection, ok/err, row_to_dict, get_next_name, audit, to_decimal, round_currency, check_required_tables)
