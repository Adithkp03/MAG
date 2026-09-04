# Phase 20 — Performance
Redis cache: backend/app/core/cache.py (Redis + in-mem fallback, cached() decorator, 60s TTL applied to autonomous intelligence). Pagination: products limit/offset, q sanitized. DB indexes: idx_products_merchant, idx_orders_merchant, idx_checkouts_merchant, idx_payments_merchant, idx_campaigns_merchant, idx_orders_merchant_created (CREATE INDEX IF NOT EXISTS on startup). EXPLAIN: GET /api/v1/debug/explain runs EXPLAIN ANALYZE JSON for tenant queries.

Files: backend/app/core/cache.py, backend/app/api/routes/products.py, backend/app/main.py:indexes+explain, backend/app/api/routes/autonomous.py:cached
