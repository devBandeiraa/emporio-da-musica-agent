# Assumptions and Data Decisions

The store's data and manual contradict each other in several places. This file records what was checked and which interpretation the agent follows. One rule settles most conflicts: **a specific section beats a general one**, and **structured fields beat free text**.

## Catalog

| Topic | What the data says | Decision |
|---|---|---|
| Product descriptions 135–144 | Names and descriptions disagree: "Music Man Bass 1X" is described as a Fender Jazz Bass, "Yamaha Bass 3X" as a 5-string Ibanez (specs say 4), a Korg synth as a Roland with 88 keys (specs say 61). | The whole block's descriptions are dropped at load time, so they can neither be quoted nor match a search. Name, price and specs remain the source of truth. |
| Catalog size | The manual claims 300+ instruments, including wind and orchestral strings. The catalog has 65 products in 6 categories; 3 categories are empty. | The agent answers from the catalog. A search for an empty category says it exists but has no products. |
| Availability | Item 96 is `active` with no stock. Item 136 is `discontinued` with 13 units. Item 130 is `coming_soon` with 2 units and appears in 2 orders. | Available means `active` **and** stock above zero. Status always wins over stock. |
| `coming_soon` | The manual does not define it. | The agent says the product is coming soon, without promising a date or availability. |
| `strings` spec | A count on guitars and basses ("6"), a material on acoustic guitars and ukuleles ("nylon"). The count of 7-string guitars is only in the name. | The search index handles both meanings. |
| Spec language | English and Portuguese are mixed ("steel", "Black", "Preto"). | Common values are translated for search only; the original value is what the agent shows. |

## Promotions and prices

| Topic | What the data says | Decision |
|---|---|---|
| Active promotions | 4 of 25 are active (products 90, 94, 121, 127). There are no date columns. | `is_active` is the only signal. "Expired" means `is_active = 0`; the agent cannot say when it ended. |
| Expired discounts | Products 93, 96 and 99 have two inactive promotions each, with different percentages. | The agent only receives the promotion's name, never the old percentage, so it cannot promise an expired discount. |
| PIX | 5% off the list price, not cumulative with promotions (§6.2). | PIX price is calculated only when there is no active promotion. |
| Installments | The table in §3 says up to 12x with a R$ 100 minimum; §3.1 sets tiers. | §3.1 applies: up to 3x, minimum R$ 50; 4x–6x, R$ 80; 7x–12x, R$ 100. The R$ 50 reading comes from "sem valor mínimo (exceto abaixo de R$ 50,00)". |
| Price filters | Customers think in final prices. | "Up to R$ X" compares against the promotional price when there is one. |

## Orders

| Topic | What the data says | Decision |
|---|---|---|
| Totals | Orders 3 and 20 differ from quantity × price (3450 vs 3498, 1400 vs 1488). `order_items` has no unit price. | The agent reports the recorded total and never recalculates: today's price says nothing about the price at purchase. |
| Orders vs manual | The 5 PIX orders show no 5% discount. Orders 9, 16 and 18 have installments below the §3.1 minimum. Order 3 delivered a `coming_soon` product. | The agent reports what is recorded and does not audit. If a customer disputes it, the case goes to a person. |
| Reference date | Orders end on 2026-03-22; the real date makes every policy window expire. | `REFERENCE_DATETIME=2026-03-25T10:00:00` is the earliest sensible "today" after the last order, and it stays configurable. |
| Return windows | The latest delivered order's 7-day window closes on 2026-02-24 and its 30-day window on 2026-03-05, both before the last order. | No reference date coherent with the data leaves a delivered order inside those windows. Orders 5, 6 and 7 are still inside the 90-day legal warranty. Tests inject other dates to cover the in-window path. |
| Receipt date | The data has no delivery date. | `estimated_delivery` stands in for receipt, only for `delivered` orders. For `shipped` orders the window has not started. |
| Windows' start | §4.1 and §8.1 count from receipt, §4.2 from purchase, §4.3 does not say. | §4.3 counts from receipt, like §4.1. |
| Purchase channel | §4.1 applies to online purchases; orders have no channel column. | Every order is treated as online, since all of them follow a shipping flow. |

## Privacy

| Topic | Decision |
|---|---|
| Order lookup | The manual has no verification procedure; §9 only lists how data is used. Requiring the order number plus the customer's e-mail or phone is a design decision based on the LGPD. |
| Duplicate e-mail | Customers 11 and 43 share `bruno.martins@jmail.com`. Customers are never searched by e-mail: the contact is compared against the owner of that order. |
| Failed lookups | A missing order and a wrong contact return the same answer, so order numbers cannot be probed. |
| Conversation history | Kept in memory only, because it holds personal data after verification. |

## Manual conflicts and gaps

| Topic | Decision |
|---|---|
| Phone | (67) 3341-4444 for calls and (67) 3321-4500 for WhatsApp, because §7 is specific to WhatsApp and §1.2 only has a generic field. |
| E-mail | `contato@emporiodamusica.com.br`, without the accent shown in §1.2. The accented form looks like a typo. |
| Opening hours | Monday to Friday 09:00–18:00, Saturday 09:00–13:00, closed on Sundays and holidays. Automatic PDF extraction misaligns this table, so the manual was transcribed and reviewed by hand. |
| Defects after 30 days | §4.2 sends the customer to the manufacturer; §8.1 grants 90 days of legal warranty. The agent explains both and offers the store's intermediation. |
| Not covered by the manual | Cancellation rules, partner stores, shipping prices outside Campo Grande and which carrier handled an order. The agent says it does not know and hands over to a person. |
| Free shipping at exactly R$ 500 | §5.1 only defines "above" and "below". The agent follows the literal text and does not promise free shipping at exactly R$ 500. |
