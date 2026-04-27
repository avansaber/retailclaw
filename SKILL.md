---
name: retailclaw
version: 1.0.0
description: Retail Management -- 87 actions across 9 domains. Pricing, promotions, loyalty programs, gift cards, merchandising, planograms, wholesale/B2B, returns/exchanges, store locations, multi-channel, procurement, and analytics.
author: AvanSaber
homepage: https://github.com/avansaber/retailclaw
source: https://github.com/avansaber/retailclaw
tier: 4
category: retail
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [retailclaw, retail, pricing, promotion, coupon, loyalty, rewards, gift-card, merchandising, planogram, category, wholesale, b2b, returns, exchange, rma, pos, margin, channel, store, procurement, shrinkage, barcode]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# retailclaw

Retail Operations Manager for RetailClaw -- AI-native retail management on ERPClaw.
Manages pricing/promotions, loyalty programs (points, tiers, gift cards), visual merchandising
(categories, planograms), wholesale/B2B (customers, pricing, orders), returns/exchanges,
multi-location store management, procurement, and retail analytics.
All financials use ERPClaw GL with Decimal precision.

### Skill Activation Triggers

Activate when user mentions: pricing, price list, promotion, coupon, discount, BOGO,
loyalty, rewards, points, tier, gift card, planogram, merchandising, display, category,
wholesale, B2B, bulk order, return, exchange, RMA, refund, store credit, margin, retail,
store location, shrinkage, barcode, procurement, inter-store transfer.

### Setup
```
python3 {baseDir}/../erpclaw/scripts/erpclaw-setup/db_query.py --action initialize-database
python3 {baseDir}/init_db.py
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start
```
--action retail-add-price-list --company-id {id} --name "Retail Standard"
--action retail-add-price-list-item --price-list-id {id} --item-name "Widget A" --rate "25.99"
--action retail-add-promotion --company-id {id} --name "Summer Sale" --promo-type percentage --discount-value "15.00" --start-date "2026-06-01" --end-date "2026-08-31"
--action retail-activate-promotion --promotion-id {id}
--action retail-add-loyalty-program --company-id {id} --name "Rewards Plus"
--action retail-add-loyalty-member --company-id {id} --program-id {id} --customer-name "Jane" --enrollment-date "2026-01-01"
```

## All 87 Actions

### Pricing (12 actions)
| Action | Description |
|--------|-------------|
| `retail-add-price-list` | Create price list |
| `retail-update-price-list` | Update price list |
| `retail-get-price-list` | Get price list details |
| `retail-list-price-lists` | List price lists |
| `retail-add-price-list-item` | Add item to price list |
| `retail-update-price-list-item` | Update price list item |
| `retail-list-price-list-items` | List price list items |
| `retail-add-promotion` | Create promotion |
| `retail-update-promotion` | Update promotion |
| `retail-list-promotions` | List promotions |
| `retail-activate-promotion` | Activate promotion |
| `retail-deactivate-promotion` | Deactivate promotion |

### Loyalty (12 actions)
| Action | Description |
|--------|-------------|
| `retail-add-loyalty-program` | Create loyalty program |
| `retail-get-loyalty-program` | Get program details |
| `retail-list-loyalty-programs` | List programs |
| `retail-add-loyalty-member` | Enroll loyalty member |
| `retail-update-loyalty-member` | Update member |
| `retail-get-loyalty-member` | Get member details |
| `retail-list-loyalty-members` | List members |
| `retail-add-loyalty-points` | Add points to member |
| `retail-redeem-loyalty-points` | Redeem points |
| `retail-add-gift-card` | Issue gift card |
| `retail-check-gift-card-balance` | Check gift card balance |
| `retail-redeem-gift-card` | Redeem gift card |

### Merchandising (8 actions)
| Action | Description |
|--------|-------------|
| `retail-add-category` | Create product category |
| `retail-update-category` | Update category |
| `retail-list-categories` | List categories |
| `retail-add-planogram` | Create planogram |
| `retail-update-planogram` | Update planogram |
| `retail-list-planograms` | List planograms |
| `retail-add-planogram-item` | Add item to planogram |
| `retail-list-planogram-items` | List planogram items |

### Wholesale (10 actions)
| Action | Description |
|--------|-------------|
| `retail-add-wholesale-customer` | Add B2B customer |
| `retail-update-wholesale-customer` | Update wholesale customer |
| `retail-list-wholesale-customers` | List wholesale customers |
| `retail-add-wholesale-price` | Set wholesale price |
| `retail-list-wholesale-prices` | List wholesale prices |
| `retail-add-wholesale-order` | Create wholesale order |
| `retail-get-wholesale-order` | Get wholesale order |
| `retail-list-wholesale-orders` | List wholesale orders |
| `retail-add-wholesale-order-item` | Add item to order |
| `retail-list-wholesale-order-items` | List order items |

### Returns & Exchanges (8 actions)
| Action | Description |
|--------|-------------|
| `retail-add-return-authorization` | Create return/RMA |
| `retail-update-return-authorization` | Update return |
| `retail-get-return-authorization` | Get return details |
| `retail-list-return-authorizations` | List returns |
| `retail-add-return-item` | Add return line item |
| `retail-list-return-items` | List return items |
| `retail-process-return` | Process return/refund |
| `retail-add-exchange` | Process exchange |

### Store Locations (9 actions)
| Action | Description |
|--------|-------------|
| `retail-add-store-location` | Add store location |
| `retail-update-store-location` | Update store location |
| `retail-list-store-locations` | List store locations |
| `retail-add-store-shift` | Add store shift |
| `retail-list-store-schedules` | List store schedules |
| `retail-get-store-inventory` | Get inventory by store |
| `retail-set-location-reorder-point` | Set reorder point |
| `retail-request-inter-store-transfer` | Request inter-store transfer |
| `retail-list-inter-store-transfers` | List transfers |

### Procurement (5 actions)
| Action | Description |
|--------|-------------|
| `retail-check-reorder-points` | Check reorder points |
| `retail-generate-purchase-suggestions` | Generate purchase suggestions |
| `retail-auto-create-purchase-orders` | Auto-create POs |
| `retail-generate-barcode-labels` | Generate barcode labels |
| `retail-list-customer-segments` | List customer segments |

### E-Commerce & Channel (7 actions)
| Action | Description |
|--------|-------------|
| `retail-import-online-orders` | Import online orders |
| `retail-fulfill-online-order` | Fulfill online order |
| `retail-sync-products-to-channel` | Sync products to channel |
| `retail-sync-inventory-to-channel` | Sync inventory to channel |
| `retail-issue-store-credit` | Issue store credit |
| `retail-check-store-credit-balance` | Check store credit |
| `retail-redeem-store-credit` | Redeem store credit |

### Shrinkage (4 actions)
| Action | Description |
|--------|-------------|
| `retail-record-shrinkage` | Record inventory shrinkage |
| `retail-list-shrinkage` | List shrinkage records |
| `retail-shrinkage-report` | Shrinkage report |
| `retail-shrinkage-by-cause-report` | Shrinkage by cause |

### Reports & Analytics (12 actions)
| Action | Description |
|--------|-------------|
| `retail-channel-performance` | Channel performance report |
| `retail-margin-analysis` | Margin analysis |
| `retail-loyalty-report` | Loyalty program report |
| `retail-category-performance` | Category performance |
| `retail-promotion-effectiveness` | Promotion effectiveness |
| `retail-inventory-turnover` | Inventory turnover |
| `retail-calculate-rfm` | Calculate RFM scores |
| `retail-multi-location-stock-report` | Multi-location stock |
| `retail-omnichannel-sales-report` | Omnichannel sales |
| `retail-channel-inventory-report` | Channel inventory |
| `retail-procurement-report` | Procurement report |
| `retail-segment-performance-report` | Segment performance |

## Technical Details (Tier 3)
**Tables (19):** All use `retailclaw_` prefix. **Script:** `scripts/db_query.py` routes to 9 modules. **Data:** Money=TEXT(Decimal), IDs=TEXT(UUID4).
