
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import Base, engine, SessionLocal
from .models.entities import Merchant, Customer, Product, Policy
from .api.routes import products, carts, checkout, orders, trust, webhooks, agent, payments, recommendations, ucp, growth, growth_agent, campaigns, evaluation, workers, autonomous, hardening

app = FastAPI(title="Merchant Autonomous Growth & Commerce Agent", version="0.21.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Observability: trace per request
from fastapi import Request
from .core.tracing import start_trace, end_trace, start_span, end_span, get_trace_id
@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    tid=start_trace(f"{request.method} {request.url.path}")
    s=start_span(f"http:{request.method} {request.url.path}", attrs={"path": str(request.url.path)})
    try:
        response=await call_next(request)
        end_span(s, status="ok", attrs={"status": response.status_code})
        response.headers["X-Trace-Id"]=tid
        return response
    except Exception as e:
        end_span(s, status="error", attrs={"error": str(e)[:200]})
        raise
    finally:
        end_trace(tid)

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
# migrate missing columns for existing Supabase DB (additive only)
try:
    from sqlalchemy import text as _text
    with engine.connect() as conn:
        for ddl in [
            "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS api_key TEXT",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS version INT DEFAULT 1",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP",
            "ALTER TABLE checkouts ADD COLUMN IF NOT EXISTS policy_version INT DEFAULT 1",
            "ALTER TABLE approvals ADD COLUMN IF NOT EXISTS decided_at TIMESTAMP",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS auto_approve_limit INT DEFAULT 500000",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS approval_limit INT DEFAULT 1000000",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS hard_block_limit INT DEFAULT 2000000",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS max_campaign_budget INT DEFAULT 1000000",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS max_daily_spend INT DEFAULT 5000000",
            "ALTER TABLE policies ADD COLUMN IF NOT EXISTS min_margin_pct INT DEFAULT 10",
            "ALTER TABLE products ADD COLUMN IF NOT EXISTS reserved INT DEFAULT 0",

        ]:
            try: conn.execute(_text(ddl)); conn.commit()
            except Exception as e: print(f"migrate skip {ddl[:30]}: {e}")
except Exception as e:
    print(f"migrate warn: {e}")

# seed on startup if empty
def seed():
    db = SessionLocal()
    try:
        if db.query(Merchant).count()==0:
            m = Merchant(id="m_demo", name="Demo Merchant", email="merchant@demo.local")
            db.add(m); db.commit()
            c = Customer(id="cust_demo", merchant_id="m_demo", name="Demo Customer", email="demo@customer.local")
            db.add(c)
            products_seed=[
                {"id":"prod_kb1","merchant_id":"m_demo","name":"Gaming Keyboard RGB","description":"Mechanical gaming keyboard with RGB, blue switches","price":249900,"category":"keyboard","stock":42},
                {"id":"prod_mouse1","merchant_id":"m_demo","name":"Wireless Gaming Mouse","description":"Ergonomic wireless mouse 16000 DPI","price":79900,"category":"mouse","stock":82},
                {"id":"prod_laptop1","merchant_id":"m_demo","name":"Gaming Laptop 16GB","description":"RTX 4060 gaming laptop","price":750000,"category":"laptop","stock":5},
                {"id":"prod_headset1","merchant_id":"m_demo","name":"Wireless Headset","description":"Noise cancelling wireless headset","price":349900,"category":"headset","stock":30},
                {"id":"prod_mousepad1","merchant_id":"m_demo","name":"XL Mousepad","description":"900x400 mousepad","price":49900,"category":"mousepad","stock":100},
                {"id":"prod_bag1","merchant_id":"m_demo","name":"Laptop Bag 15in","description":"Water resistant laptop bag","price":149900,"category":"bag","stock":25},
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
    return {"status":"ok", "phase":"2 razorpay", "version": app.version, "groq": "configured" if settings.groq_api_key and "xxx" not in settings.groq_api_key else "missing - set GROQ_API_KEY", "razorpay": "live" if has_keys() else "mock (set RAZORPAY_KEY_ID)", "webhook": "/api/v1/webhooks/razorpay", "db": settings.database_url.split("@")[-1][:40], "migrations": "alembic upgrade head", "tracing": "agent_execution_tracing (set OTEL_EXPORTER_OTLP_ENDPOINT for OTel)"}

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

# UCP stub for Phase 6 - advertises capabilities
@app.get("/.well-known/ucp")
def ucp_profile():
    return {
        "ucp_version":"1.0-draft",
        "merchant_id":"m_demo",
        "capabilities":["discover","catalog","checkout","payment"],
        "endpoints":{"checkout":"/api/v1/ucp/checkout","catalog":"/api/v1/ucp/catalog","discover":"/api/v1/ucp/discover","internal_checkout":"/api/v1/checkout","webhooks":"/api/v1/webhooks/razorpay","trusted_ui":"/api/v1/checkout/{id}/approve"}
    }
