
import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.entities import Product, AgentSession, AgentRun, AgentMessage, AgentToolCall, AuditEvent
from ..services.growth_intelligence import compute_product_metrics, compute_customer_metrics, rank_candidates
from .groq_client import get_groq_client

GROWTH_SYSTEM = """You are Growth Agent for Merchant Autonomous Growth. Find evidence-based opportunities.

Tools:
- get_revenue_metrics(merchant_id): total revenue, AOV, conversion, order count
- get_product_metrics(merchant_id): per-product conversion/attach/stock
- find_growth_opportunities(merchant_id): low attach high stock gaps
- get_cross_sell_candidates(category, merchant_id): ranked candidates with affinity evidence
- estimate_campaign(target_category, discount): expected revenue impact from history

CRITICAL: merchant_id is ALWAYS "m_demo" - never use merchant_123 or any other ID.
Workflow: Always start with get_revenue_metrics with merchant_id="m_demo", then get_product_metrics or find_growth_opportunities, then get_cross_sell_candidates for top gap, then estimate_campaign. Always cite numbers: attach 57% vs baseline, orders 12, etc. Never invent. Propose one concrete campaign.
"""

GROWTH_TOOLS = [
    {"type":"function","function":{"name":"get_revenue_metrics","description":"Get merchant revenue metrics","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_product_metrics","description":"Per-product conversion and attach","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"find_growth_opportunities","description":"Find low attach high stock opportunities","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_cross_sell_candidates","description":"Ranked cross-sell with evidence","parameters":{"type":"object","properties":{"category":{"type":"string"},"merchant_id":{"type":"string"}},"required":["category"]}}},
    {"type":"function","function":{"name":"estimate_campaign","description":"Estimate campaign impact","parameters":{"type":"object","properties":{"target_category":{"type":"string"},"discount":{"type":"integer"}},"required":["target_category"]}}},
]

def growth_gateway(db: Session, tool: str, args: dict):
    mid=args.get("merchant_id","m_demo")
    # force to m_demo if hallucinated
    from ..models.entities import Merchant
    if not db.query(Merchant).filter(Merchant.id==mid).first():
        mid="m_demo"
    if tool=="get_revenue_metrics":
        row=db.execute(text("""
            SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev, COALESCE(AVG(total),0) as aov
            FROM orders WHERE merchant_id=:mid AND status='paid'
        """), {"mid": mid}).mappings().first()
        return {"output": {"order_count": row["cnt"], "revenue_paise": int(row["rev"]), "revenue_inr": round(float(row["rev"])/100,2), "aov_inr": round(float(row["aov"])/100,2) if row["aov"] else 0}}
    elif tool=="get_product_metrics":
        return {"output": compute_product_metrics(db, mid)}
    elif tool=="find_growth_opportunities":
        opp=db.execute(text("""
            SELECT p.category, COUNT(DISTINCT o.id) as orders, AVG(p.stock) as avg_stock
            FROM products p LEFT JOIN cart_items ci ON ci.product_id=p.id LEFT JOIN carts c ON ci.cart_id=c.id LEFT JOIN checkouts ch ON ch.cart_id=c.id LEFT JOIN orders o ON o.checkout_id=ch.id
            WHERE p.merchant_id=:mid GROUP BY p.category
        """), {"mid": mid}).mappings().all()
        # use real pipeline for opportunities
        from ..services.growth_intelligence import compute_product_metrics as cpm
        data=cpm(db, mid)
        opps=[]
        for m in data["metrics"]:
            if m["attach_rate"] < 0.3 and m["stock"]>30:
                opps.append({"category": m["category"], "product": m["name"], "attach_rate": m["attach_rate"], "conversion": m["conversion_rate"], "stock": m["stock"], "evidence": f"attach {m['attach_rate']:.0%} vs avg, {m['order_count']} orders"})
        return {"output": {"opportunities": opps[:3], "evidence_count": len(opps)}}
    elif tool=="get_cross_sell_candidates":
        cat=args.get("category","keyboard")
        cands=rank_candidates(db, cat, mid, limit=3)
        return {"output": {"category": cat, "candidates": cands}}
    elif tool=="estimate_campaign":
        cat=args.get("target_category","keyboard"); disc=args.get("discount",10)
        # estimate: orders_with_category * attach * discount lift
        data=compute_product_metrics(db, "m_demo")
        base=next((m for m in data["metrics"] if m["category"].lower()==cat.lower()), None)
        if not base:
            return {"output": {"estimated_lift": "unknown", "reason": "no history"}}
        # simple model: attach 0.57 * orders 7 * avg price 799 * discount factor
        lift_orders = int(base["orders_with_category"] * 0.3)  # 30% of buyers add cross-sell with campaign
        avg_price=79900  # mouse price
        incremental = lift_orders * avg_price * (1 - disc/100)
        return {"output": {"target": cat, "discount": disc, "base_orders": base["orders_with_category"], "estimated_incremental_paise": int(incremental), "estimated_incremental_inr": round(incremental/100,2), "reason": f"{lift_orders} incremental adds from {base['orders_with_category']} base orders at {disc}% discount"}}
    else:
        return {"error": f"unknown {tool}"}

def run_growth_agent(db: Session, merchant_id: str="m_demo", user_message: str="Find growth opportunities"):
    client=get_groq_client()
    sess=db.query(AgentSession).filter(AgentSession.merchant_id==merchant_id).first()
    if not sess:
        sess=AgentSession(merchant_id=merchant_id); db.add(sess); db.commit(); db.refresh(sess)
    run=AgentRun(session_id=sess.id, merchant_id=merchant_id, user_message=user_message, status="running")
    db.add(run); db.commit(); db.refresh(run)
    db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="user", content=user_message)); db.commit()
    if not client:
        out=growth_gateway(db, "find_growth_opportunities", {"merchant_id": merchant_id})
        run.final_reply=str(out["output"]); run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
        return {"run": run, "tool_calls": [], "fallback": True}
    messages=[{"role":"system","content": GROWTH_SYSTEM}, {"role":"user","content": user_message}]
    tool_log=[]
    for _ in range(6):
        resp=client.chat.completions.create(model="openai/gpt-oss-20b", messages=messages, tools=GROWTH_TOOLS, tool_choice="auto", temperature=0.2, max_tokens=900)
        msg=resp.choices[0].message
        db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="assistant", content=msg.content or "")); db.commit()
        if not msg.tool_calls:
            run.final_reply=msg.content or "Growth analysis complete"; run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
            break
        for tc in msg.tool_calls:
            fname=tc.function.name
            try: args=json.loads(tc.function.arguments or "{}")
            except: args={}
            res=growth_gateway(db, fname, args)
            tcr=AgentToolCall(run_id=run.id, session_id=sess.id, tool=fname, input=args, output=res)
            db.add(tcr); db.commit()
            tool_log.append({"tool": fname, "input": args, "output": res})
            messages.append({"role":"assistant","content": msg.content or "", "tool_calls": [{"id": tc.id, "type":"function","function":{"name": fname, "arguments": tc.function.arguments}}]})
            messages.append({"role":"tool","tool_call_id": tc.id, "content": json.dumps(res)[:2000]})
            db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="tool", content=json.dumps(res)[:2000], tool_call_id=tc.id)); db.commit()
    else:
        run.final_reply=f"Completed {len(tool_log)} growth steps"; run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
    return {"run": run, "tool_calls": tool_log}
