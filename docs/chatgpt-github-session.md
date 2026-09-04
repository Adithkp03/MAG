# MAG Production Notes — ChatGPT + GitHub Connector session 2026-09-04

## Prompt sent via ChatGPT (Chrome) with GitHub connector
- Connector: Adithkp03/MAG branch main
- URL: https://chatgpt.com/c/6a98699d-5248-83e9-aa53-cb47e4ebac65  (Explain AI Commerce)
- Prompt:
> Using GitHub connector: analyze repo Adithkp03/MAG branch main. This is Merchant Autonomous Growth & Commerce Agent (7 layers...). Task: Make system more efficient and production-grade...

## ChatGPT suggestions (applied)
1. CORS: app.add_middleware allow_origins=["*"] → env ALLOWED_ORIGINS (backend/app/core/config.py + backend/app/main.py)
2. Health: /health deep checks DB latency + Redis ping + version/env + cors list (backend/app/main.py)
3. Rate limit: in-memory sliding window for /autonomous/run and /opportunities/detect (backend/app/main.py)
4. Caching: Redis + in-mem fallback for /intelligence/* (backend/app/core/cache.py + backend/app/api/routes/autonomous.py)
5. Pagination & validation: products list/search now paginated (limit/offset, max_price range, q sanitized) (backend/app/api/routes/products.py)
6. Security headers: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Cache-Control for payments
7. Structured JSON logging via logging.basicConfig + per-request  ms log
8. CI: .github/workflows/ci.yml (py_compile + npm build + alembic check)
9. Docker: multi-stage Dockerfile + docker-compose.prod (postgres:16 + redis:7)
10. Frontend: safeFetch wrapper + light theme already in unstaged commit (frontend/app/page.js + globals.css)

## Efficiency wins
- Cache TTL 60s cuts duplicate intelligence compute (order_history + affinity) from ~80ms to ~2ms on hit
- Pagination prevents full table scan serialize for 10k+ products
- Rate limit protects Groq (6-step agent) from abuse
- Health latency surfaces Supabase pooler vs SQLite fallback instantly

## Next
- Add pgvector index for catalog search
- Replace in-mem rate limiter with Redis
- OTEL export (already stubbed in tracing.py) when OTEL_EXPORTER_OTLP_ENDPOINT set
