
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product, Cart, AgentSession, AuditEvent
from ...services.catalog import search_products
from ...services.recommendation import recommend_cross_sell
from ...trust.policy import check_policy
from ...core.events import publish
from ...agent.groq_client import get_groq_client, SYSTEM_PROMPT, TOOLS_SCHEMA
import json

router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/chat")
def chat(payload: dict, db: Session = Depends(get_db)):
    merchant_id = payload.get("merchant_id","m_demo")
    customer_id = payload.get("customer_id")
    message = payload.get("message","")
    session_id = payload.get("session_id")
    # ensure session
    if session_id:
        sess = db.query(AgentSession).filter(AgentSession.id==session_id).first()
    else:
        sess = None
    if not sess:
        sess = AgentSession(merchant_id=merchant_id, customer_id=customer_id)
        db.add(sess); db.commit(); db.refresh(sess)

    # Groq path if key present
    client = get_groq_client()
    if client:
        try:
            resp = client.chat.completions.create(model=payload.get("model","openai/gpt-oss-20b"), messages=[{"role":"system","content":SYSTEM_PROMPT},{"role":"user","content":message}], tools=TOOLS_SCHEMA, tool_choice="auto", temperature=0.2, max_tokens=800)
            msg = resp.choices[0].message
            # if tool calls, execute first one via our services
            if hasattr(msg,"tool_calls") and msg.tool_calls:
                tc = msg.tool_calls[0]
                fn = tc.function.name
                args = json.loads(tc.function.arguments or "{}")
                result = execute_tool(fn, args, db, merchant_id)
                return {"session_id": sess.id, "reply": msg.content or f"Executing {fn}", "tool_call": {"name": fn, "args": args, "result": result}, "groq": True}
            return {"session_id": sess.id, "reply": msg.content, "groq": True}
        except Exception as e:
            return {"session_id": sess.id, "reply": f"Groq error: {e}", "fallback": True}

    # fallback deterministic: simple keyword search + cross-sell
    q = message.lower()
    # naive parse max_price
    import re
    max_price=None
    m=re.search(r"under\s*₹?\s*(\d+)", q)
    if m: max_price=int(m.group(1))*100
    prods = search_products(db, merchant_id, q="", max_price=max_price)
    # also try keyword search from message nouns
    if not prods:
        prods = db.query(Product).limit(3).all()
    # cross-sell if one category dominant
    recs=[]
    if prods:
        recs = recommend_cross_sell(prods[0].category or "general", db.query(Product).all(), limit=2)
    return {"session_id": sess.id, "reply": f"Found {len(prods)} products. Top: {prods[0].name if prods else 'none'}", "products": prods, "recommendations": recs, "groq": False}

def execute_tool(name, args, db, merchant_id):
    if name=="search_products":
        return search_products(db, merchant_id, args.get("q",""), args.get("category",""), args.get("max_price"))
    if name=="get_product":
        return db.query(Product).filter(Product.id==args["product_id"]).first()
    if name=="create_cart":
        c=Cart(merchant_id=args.get("merchant_id",merchant_id), customer_id=args.get("customer_id"))
        db.add(c); db.commit(); db.refresh(c)
        return c
    if name=="add_to_cart":
        from .carts import add_item  # not used directly
        # simplified
        return {"note":"use POST /carts/{id}/items for authoritative add"}
    return {"error":"unknown tool"}

@router.get("/sessions/{session_id}/audit")
def session_audit(session_id: str, db: Session = Depends(get_db)):
    return db.query(AuditEvent).filter(AuditEvent.payload.contains(session_id) if False else True).limit(20).all()
