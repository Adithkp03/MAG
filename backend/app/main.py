from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import Base, engine, SessionLocal
from .models.entities import Merchant, Customer, Product, Policy
from .api.routes import products, carts, checkout, orders, trust, webhooks, agent, payments, recommendations, ucp, growth, growth_agent, campaigns, evaluation, workers, autonomous, hardening
import logging, time
from .core.config import settings

# structured logging
import json as _json
class JsonFormatter(logging.Formatter):
    def format(self, record):
        obj={"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        if hasattr(record, "trace_id"): obj["trace_id"]=record.trace_id
        if record.exc_info and record.exc_info[0]: obj["exc"]=self.formatException(record.exc_info)
        return _json.dumps(obj)
handler=logging.StreamHandler()
try:
    if settings.env=="production":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
except: pass
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), handlers=[handler], force=True)
logger = logging.getLogger("mag")

app = FastAPI(title="Merchant Autonomous Growth & Commerce Agent", version="0.22.0")

# --- Production CORS: restrict to ALLOWED_ORIGINS, env-driven ---
origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] if settings.allowed_origins else []
if settings.env == "production" and "*" in origins:
    raise RuntimeError("ALLOWED_ORIGINS must not be '*' in production")
# in dev allow all if explicit
if settings.env != "production" and "*" in origins:
    cors_origins = ["*"]
else:
    cors_origins = origins if origins else ["http://localhost:3000", "http://127.0.0.1:3000"]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
logger.info(f"CORS origins: {cors_origins} env={settings.env}")

# --- Security headers + trace per request ---
from fastapi import Request
from .core.tracing import start_trace, end_trace, start_span, end_span, get_trace_id
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    # simple rate-limit via in-memory counter (production: use Redis)
    tid=start_trace(f"{request.method} {request.url.path}")
    s=start_span(f"http:{request.method} {request.url.path}", attrs={"path": str(request.url.path)})
    start = time.time()
    try:
        response=await call_next(request)
        end_span(s, status="ok", attrs={"status": response.status_code})
        response.headers["X-Trace-Id"]=tid
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["X-Frame-Options"]="DENY"
        response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"
        response.headers["Cache-Control"]="no-store" if request.url.path.startswith("/api/v1/checkout") or request.url.path.startswith("/api/v1/payments") else "no-cache"
        logger.info(f"{request.method} {request.url.path} {response.status_code} {round((time.time()-start)*1000)}ms trace={tid}")
        return response
    except Exception as e:
        end_span(s, status="error", attrs={"error": str(e)[:200]})
        logger.exception(f"request failed {request.method} {request.url.path}: {e}")
        raise
    finally:
        end_trace(tid)

# --- Simple in-memory rate limiter for expensive endpoints ---
from collections import defaultdict
import time as _time
_rate = defaultdict(list)
def _check_rate(key: str, limit_per_min: int = 30) -> bool:
    now = _time.time()
    window = 60
    lst = _rate[key]
    # prune
    while lst and lst[0] < now - window:
        lst.pop(0)
    if len(lst) >= limit_per_min:
        return False
    lst.append(now)
    return True

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    # only limit autonomous/run and checkout creation
    if request.url.path in ("/api/v1/autonomous/run", "/api/v1/opportunities/detect", "/api/v1/growth-agent/run", "/api/v1/campaigns"):
        ip = request.client.host if request.client else "unknown"
        if not _check_rate(f"rl:{ip}:{request.url.path}", limit_per_min=20):
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=429, content={"code":"rate_limited","message":"Too many requests, retry after 60s"})
    return await call_next(request)

@app.get("/api/v1/traces")
def list_traces_ep(limit: int=20):
    from .core.tracing import list_traces, label
    return {"traces": list_traces(limit), "tracing": label()}

@app.get("/api/v1/traces/{trace_id}")
def get_trace_ep(trace_id: str):
    from .core.tracing import get_trace
    tr=get_trace(trace_id)
    if not tr: return {"error":"not found"}
    return tr

# P0: create new tables Approval/WebhookEvent and handle missing columns via create_all (idempotent)
Base.metadata.create_all(bind=engine)
# Phase 19-20: tenant isolation + performance indexes (idempotent)
try:
    from sqlalchemy import text as _text
    with engine.connect() as conn:
        for ddl in [
            "CREATE INDEX IF NOT EXISTS idx_products_merchant ON products(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_merchant ON orders(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_checkouts_merchant ON checkouts(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_payments_merchant ON payments(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_campaigns_merchant ON campaigns(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_customers_merchant ON customers(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_opportunities_merchant ON opportunities(merchant_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_merchant_created ON orders(merchant_id, created_at DESC)",
        ]:
            try: conn.execute(_text(ddl)); conn.commit()
            except Exception as e: print(f"index skip {ddl[:40]}: {e}")
except Exception as e:
    print(f"index creation warn: {e}")
# migrate missing columns for existing DBs (additive only, sqlite + postgres compatible)
def _ensure_column(table: str, column: str, ddl_type: str):
    from sqlalchemy import text as _text
    # check existence on a throwaway connection
    try:
        with engine.connect() as conn:
            try:
                cols = [r[1] for r in conn.execute(_text(f"PRAGMA table_info({table})")).fetchall()]
            except Exception:
                cols = []
                try:
                    conn.rollback()
                except Exception:
                    pass
            if cols and column in cols:
                return
            if not cols:
                # non-sqlite backend: check information_schema
                try:
                    hit = conn.execute(_text(
                        "SELECT 1 FROM information_schema.columns WHERE table_name=:t AND column_name=:c"),
                        {"t": table, "c": column}).first()
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    if hit:
                        return
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
    except Exception as e:
        print(f"migrate warn {table}.{column}: {e}")
        return
    # add on a fresh transaction; each attempt isolated
    for stmt in (f'ALTER TABLE {table} ADD COLUMN "{column}" {ddl_type}',
                 f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{column}" {ddl_type}'):
        try:
            with engine.begin() as conn:
                conn.execute(_text(stmt))
            return
        except Exception as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                return
            last = e
    print(f"migrate skip {table}.{column}: {last}")

for _t, _c, _d in [
    ("merchants", "api_key", "TEXT"),
    ("merchants", "api_key_hash", "TEXT"),
    ("merchants", "api_key_prefix", "TEXT"),
    ("policies", "version", "INT DEFAULT 1"),
    ("policies", "updated_at", "TIMESTAMP"),
    ("checkouts", "policy_version", "INT DEFAULT 1"),
    ("approvals", "decided_at", "TIMESTAMP"),
    ("approvals", "campaign_id", "TEXT"),
    ("approvals", "action_type", "TEXT"),
    ("approvals", "expires_at", "TIMESTAMP"),
    ("policies", "auto_approve_limit", "INT DEFAULT 500000"),
    ("policies", "approval_limit", "INT DEFAULT 1000000"),
    ("policies", "hard_block_limit", "INT DEFAULT 2000000"),
    ("policies", "max_campaign_budget", "INT DEFAULT 1000000"),
    ("policies", "max_daily_spend", "INT DEFAULT 5000000"),
    ("policies", "min_margin_pct", "INT DEFAULT 10"),
    ("products", "reserved", "INT DEFAULT 0"),
    ("orders", "campaign_id", "TEXT"),
    ("webhook_events", "status", "TEXT DEFAULT 'received'"),
    ("webhook_events", "attempts", "INT DEFAULT 0"),
    ("webhook_events", "last_error", "TEXT DEFAULT ''"),
    ("campaigns", "expected_incremental_margin", "INT DEFAULT 0"),
    ("campaigns", "budget_paise", "INT DEFAULT 0"),
    ("campaigns", "cost_paise", "INT DEFAULT 0"),
    ("campaigns", "policy_version", "INT DEFAULT 1"),
    ("campaigns", "experiment_ratio", "FLOAT DEFAULT 0.1"),
    ("campaigns", "simulation_mode", "BOOLEAN DEFAULT TRUE"),
    ("campaigns", "approved_amount", "INT"),
    ("campaigns", "action_hash", "TEXT"),
    ("campaign_audiences", "customer_id", "TEXT"),
    ("campaign_audiences", "group", "TEXT"),
    ("campaign_audiences", "assigned_at", "TIMESTAMP"),
    ("campaign_audiences", "exposed_at", "TIMESTAMP"),
    ("campaign_audiences", "viewed_at", "TIMESTAMP"),
    ("campaign_audiences", "clicked_at", "TIMESTAMP"),
    ("campaign_audiences", "added_at", "TIMESTAMP"),
    ("campaign_audiences", "purchased_at", "TIMESTAMP"),
    ("campaign_audiences", "order_id", "TEXT"),
    ("campaign_audiences", "is_simulated", "BOOLEAN DEFAULT FALSE"),
    ("campaign_metrics", "treatment_eligible", "INT DEFAULT 0"),
    ("campaign_metrics", "treatment_purchases", "INT DEFAULT 0"),
    ("campaign_metrics", "treatment_revenue", "INT DEFAULT 0"),
    ("campaign_metrics", "treatment_margin", "INT DEFAULT 0"),
    ("campaign_metrics", "control_eligible", "INT DEFAULT 0"),
    ("campaign_metrics", "control_purchases", "INT DEFAULT 0"),
    ("campaign_metrics", "control_revenue", "INT DEFAULT 0"),
    ("campaign_metrics", "control_margin", "INT DEFAULT 0"),
    ("campaign_metrics", "incremental_orders", "INT DEFAULT 0"),
    ("campaign_metrics", "incremental_revenue", "INT DEFAULT 0"),
    ("campaign_metrics", "incremental_margin", "INT DEFAULT 0"),
    ("campaign_metrics", "ci_low", "FLOAT"),
    ("campaign_metrics", "ci_high", "FLOAT"),
    ("campaign_metrics", "sample_adequate", "BOOLEAN DEFAULT FALSE"),
    ("campaign_metrics", "simulation_mode", "BOOLEAN DEFAULT TRUE"),
]:
    _ensure_column(_t, _c, _d)
try:
    from .models.entities import LearningState  # noqa: F401 - ensure table via create_all below
    Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"learning_state create warn: {e}")

# seed on startup if empty
def seed():
    db = SessionLocal()
    try:
        from .models.entities import hash_api_key
        if db.query(Merchant).count()==0:
            m = Merchant(id="m_demo", name="Demo Merchant", email="merchant@demo.local")
            # demo key: stored as hash; raw value only in backend/.env for local dev
            import os
            raw = os.getenv("DEMO_MERCHANT_KEY", "demo_key_123")
            m.api_key = None  # no plaintext at rest
            m.api_key_hash = hash_api_key(raw)
            m.api_key_prefix = raw[:6]
            db.add(m); db.commit()
            c = Customer(id="cust_demo", merchant_id="m_demo", name="Demo Customer", email="demo@customer.local")
            db.add(c)
            products_seed=[
                {"id":"prod_kb1","merchant_id":"m_demo","name":"Gaming Keyboard RGB","description":"Mechanical gaming keyboard with RGB, blue switches","price":249900,"cost_price":164934,"category":"keyboard","stock":42},
                {"id":"prod_mouse1","merchant_id":"m_demo","name":"Wireless Gaming Mouse","description":"Ergonomic wireless mouse 16000 DPI","price":79900,"cost_price":43945,"category":"mouse","stock":82},
                {"id":"prod_laptop1","merchant_id":"m_demo","name":"Gaming Laptop 16GB","description":"RTX 4060 gaming laptop","price":750000,"cost_price":637500,"category":"laptop","stock":5},
                {"id":"prod_headset1","merchant_id":"m_demo","name":"Wireless Headset","description":"Noise cancelling wireless headset","price":349900,"cost_price":209940,"category":"headset","stock":30},
                {"id":"prod_mousepad1","merchant_id":"m_demo","name":"XL Mousepad","description":"900x400 mousepad","price":49900,"cost_price":19960,"category":"mousepad","stock":100},
                {"id":"prod_bag1","merchant_id":"m_demo","name":"Laptop Bag 15in","description":"Water resistant laptop bag","price":149900,"cost_price":89940,"category":"bag","stock":25},
            ]
            for p in products_seed:
                db.add(Product(**p))
            db.add(Policy(merchant_id="m_demo", max_transaction=500000, max_discount=15, auto_approve=True))
            db.commit()
            print("seeded demo merchant/products")
    finally:
        db.close()
seed()

app.include_router(products.router, prefix="/api/v1")
app.include_router(carts.router, prefix="/api/v1")
app.include_router(checkout.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(trust.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(agent.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
app.include_router(ucp.router, prefix="/api/v1")
app.include_router(growth.router)
app.include_router(growth_agent.router)
app.include_router(campaigns.router)
app.include_router(workers.router, prefix="/api/v1")
app.include_router(autonomous.router)
app.include_router(hardening.router)
app.include_router(evaluation.router, prefix="/api/v1")

@app.get("/health")
def health():
    from .core.config import settings
    from .services.razorpay_adapter import has_keys
    # deep checks: db + redis
    db_ok = True
    db_latency_ms = None
    redis_ok = None
    try:
        t0 = time.time()
        with engine.connect() as conn:
            from sqlalchemy import text as _t
            conn.execute(_t("SELECT 1"))
        db_latency_ms = round((time.time()-t0)*1000,1)
    except Exception as e:
        db_ok = False
        logger.warning(f"health db check failed: {e}")
    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False if "redis" in settings.redis_url else None
    return {"status":"ok" if db_ok else "degraded", "phase":"2 razorpay", "version": app.version, "env": settings.env, "groq": "configured" if settings.groq_api_key and "xxx" not in settings.groq_api_key else "missing - set GROQ_API_KEY", "razorpay": "live" if has_keys() else "mock (set RAZORPAY_KEY_ID)", "webhook": "/api/v1/webhooks/razorpay", "db": settings.database_url.split("@")[-1][:40], "db_ok": db_ok, "db_latency_ms": db_latency_ms, "redis_ok": redis_ok, "cache_ttl": settings.cache_ttl_seconds, "migrations": "alembic upgrade head", "tracing": "agent_execution_tracing (set OTEL_EXPORTER_OTLP_ENDPOINT for OTel)", "cors": cors_origins}

@app.get("/health/live")
def health_live():
    return {"status":"ok", "check":"live", "version": app.version}

@app.get("/health/ready")
def health_ready():
    db_ok=True; redis_ok=None; latency=None
    try:
        t0=time.time()
        with engine.connect() as conn:
            from sqlalchemy import text as _t
            conn.execute(_t("SELECT 1"))
        latency=round((time.time()-t0)*1000,1)
    except Exception as e:
        db_ok=False
    try:
        import redis as _r
        from .core.config import settings
        r=_r.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1)
        r.ping(); redis_ok=True
    except: redis_ok=False
    ready=db_ok and (redis_ok in (True, None) or redis_ok)
    return {"status":"ready" if ready else "not_ready", "db_ok": db_ok, "redis_ok": redis_ok, "db_latency_ms": latency, "version": app.version}

@app.get("/api/v1/debug/explain")
def debug_explain():
    # Phase 20: EXPLAIN ANALYZE for tenant-isolated queries — requires merchant_id
    from sqlalchemy import text as _t
    from .core.database import SessionLocal as SL
    s=SL()
    try:
        out={}
        for q, params in [
            ("SELECT * FROM products WHERE merchant_id=:mid LIMIT 20", {"mid":"m_demo"}),
            ("SELECT * FROM orders WHERE merchant_id=:mid ORDER BY created_at DESC LIMIT 20", {"mid":"m_demo"}),
            ("SELECT merchant_id, COUNT(*) FROM orders WHERE merchant_id=:mid GROUP BY merchant_id", {"mid":"m_demo"}),
        ]:
            try:
                rows=s.execute(_t(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {q}"), params).fetchall()
                out[q[:40]]=rows[0][0] if rows else "no plan"
            except Exception as e:
                out[q[:40]]=f"explain failed: {e}"
        return {"explain": out, "indexes": "products(merchant_id), orders(merchant_id), checkouts(merchant_id), payments(merchant_id), campaigns(merchant_id)"}
    finally:
        s.close()

@app.get("/")
def root():
    return {"name":"Merchant Autonomous Growth & Commerce Agent","docs":"/docs","health":"/health","phase":"0-2 Razorpay adapter live, next: Phase 2 Razorpay"}

@app.get("/api/v1/events")
def events(limit: int=20):
    from .core.events import list_events
    return list_events(limit)

@app.get("/api/v1/events/health")
def events_health():
    from .core.events import health as ev_health
    return ev_health()


@app.get("/api/v1/events/stream/{event_type}")
def stream_by_type(event_type: str, limit: int=20):
    from .core.events import list_stream
    return {event_type: list_stream(event_type, limit)}

# UCP ecosystem profile — discoverable by external AI (Full UCP Fix 8)
@app.get("/.well-known/ucp")
def ucp_profile():
    return {
        "ucp_version": "1.0-draft",
        "merchant_id": "m_demo",
        "merchant_name": "Demo Merchant",
        "description": "Merchant Autonomous Agent — full UCP ecosystem. External AI can discover catalog, create checkout, and complete payment entirely via UCP without calling custom internal endpoints. Commerce Core is canonical.",
        "capabilities": ["discover", "catalog", "checkout", "payment", "policy", "approval", "trusted_ui"],
        "currency": "INR",
        "payment_methods": ["razorpay"],
        "endpoints": {
            "profile": "/.well-known/ucp",
            "discover": "/api/v1/ucp/discover",
            "catalog": "/api/v1/ucp/catalog",
            "checkout_create": "POST /api/v1/ucp/checkout",
            "checkout_get": "GET /api/v1/ucp/checkout/{id}",
            "checkout_update": "PUT /api/v1/ucp/checkout/{id}",
            "checkout_complete": "POST /api/v1/ucp/checkout/{id}/complete",
            "checkout_cancel": "POST /api/v1/ucp/checkout/{id}/cancel",
            "trusted_ui": "/api/v1/checkout/{id}/approve",
            "webhooks": "/api/v1/webhooks/razorpay",
        },
        "flow": {
            "1_discover": "GET /.well-known/ucp -> read capabilities + endpoints",
            "2_catalog": "GET /api/v1/ucp/catalog?q=keyboard&merchant_id=m_demo -> list products",
            "3_create": "POST /api/v1/ucp/checkout {merchant_id, customer_id, items:[{product_id, quantity}], continue_url, idempotency_key}",
            "4_get": "GET /api/v1/ucp/checkout/{id}",
            "5_update": "PUT /api/v1/ucp/checkout/{id} {items}",
            "6_complete": "POST /api/v1/ucp/checkout/{id}/complete -> Razorpay order via Commerce Core",
            "7_cancel": "POST /api/v1/ucp/checkout/{id}/cancel",
            "approval": "If 402 approval_required -> POST /api/v1/checkout/{id}/approve with X-Approved-By header, then retry complete",
        },
        "continue_url": {
            "description": "Pass continue_url in POST /api/v1/ucp/checkout to receive buyer redirect URL; echoed in checkout resource and respected on complete.",
            "param": "continue_url",
            "example": "https://buyer.example.com/return?session=abc",
        },
        "internals": "All UCP routes call Commerce Core (services/commerce.py + services/catalog.py) directly — no delegation to custom /api/v1/checkout router. Orders and payments are created via canonical services.",
        "example_create": {
            "method": "POST",
            "url": "/api/v1/ucp/checkout",
            "body": {"merchant_id": "m_demo", "customer_id": "cust_demo", "items": [{"product_id": "prod_kb1", "quantity": 1}], "continue_url": "https://buyer.example.com/return", "idempotency_key": "ucp_demo_001"},
        },
    }
