# Realistic Merchant Dataset — Phase 2

Generated deterministically with `--seed 42`. Do not edit manually — regenerate via simulator.

## Generation

```
python backend/scripts/seed_realistic.py --seed 42        # generate CSVs only
python backend/scripts/seed_realistic.py --seed 42 --reset  # also seed DB (Supabase Postgres)
```

- Seed 42 is canonical for evaluation; CI and `FINAL_ACCEPTANCE.md` use it.
- Deterministic: same seed → same SHA256 for `products.csv` (`81445a...`) and same counts.
- Merchant-isolated: `m_demo` (24 products, 120 customers, ~550 orders) and `m_acme` (18 products, 60 customers, ~190 orders) have no overlapping data; growth/runtime queries filter by `merchant_id`.

## Files

- `merchants.csv` — 2 merchants (m_demo, m_acme)
- `products.csv` — 42 products across 8 categories (keyboard, mouse, laptop, headset, mousepad, bag, monitor, chair). Columns: `id,merchant_id,name,category,price,cost_price,margin_pct,stock,description`. `cost_price` is used in Phase 3 economics; `stock` inversely correlated with price + seasonal noise.
- `customers.csv` — 180 customers, realistic name/email distribution
- `orders.csv` — 742 orders over 120 days, weekly seasonality (weekend +15%), month-end +10%, 0.05%/day growth trend
- `order_items.csv` — 967 items with affinity matrix (e.g. laptop→mouse 45%, laptop→bag 35%) and basket 1-3 items, cheap items sometimes qty 2
- `summary.json` — counts + seed

## Realism invariants (checked in evaluation)

- Categories have distinct price bands (e.g. laptop 65k–110k INR, mouse 399–1299 INR)
- Margins per category hint (laptop 12-15%, mouse 45-50%, mousepad 60%) with ±5% noise, stored as `cost_price` + `margin_pct`
- Orders join to existing `carts/checkouts/payments` so growth intelligence can compute revenue, AOV, attachment
- Determinism: `sha256sum data/products.csv` stable across runs; `python backend/scripts/seed_realistic.py --seed 42` twice yields identical files
- Tenant isolation: `SELECT COUNT(*) FROM products WHERE merchant_id='m_acme'` ≠ `m_demo`; cross-merchant queries must filter by authenticated `merchant_id` (Phase 1)
