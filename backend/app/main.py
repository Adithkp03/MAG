
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .core.database import Base, engine, SessionLocal
from .models.entities import Merchant, Customer, Product, Policy
from .api.routes import products, carts, checkout, orders, trust, webhooks, agent, payments, recommendations, ucp

app = FastAPI(title="Merchant Autonomous Growth & Commerce Agent", version="0.4.0 Phase5-Growth")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

Base.metadata.create_all(bind=engine)

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

@app.get("/health")
def health():
    from .core.config import settings
    from .services.razorpay_adapter import has_keys
    return {"status":"ok", "phase":"2 razorpay", "version": app.version, "groq": "configured" if settings.groq_api_key and "xxx" not in settings.groq_api_key else "missing - set GROQ_API_KEY", "razorpay": "live" if has_keys() else "mock (set RAZORPAY_KEY_ID)", "webhook": "/api/v1/webhooks/razorpay", "db": settings.database_url.split("@")[-1][:40]}

@app.get("/")
def root():
    return {"name":"Merchant Autonomous Growth & Commerce Agent","docs":"/docs","health":"/health","phase":"0-2 Razorpay adapter live, next: Phase 2 Razorpay"}

@app.get("/api/v1/events")
def events(limit: int=20):
    from .core.events import list_events
    return list_events(limit)

# UCP stub for Phase 6 - advertises capabilities
@app.get("/.well-known/ucp")
def ucp_profile():
    return {
        "ucp_version":"1.0-draft",
        "merchant_id":"m_demo",
        "capabilities":["discover","catalog","checkout","payment"],
        "endpoints":{"checkout":"/api/v1/checkout","products":"/api/v1/products","webhooks":"/api/v1/webhooks/razorpay","recommendations":"/api/v1/recommendations/cross-sell","payments":"/api/v1/payments"}
    }
