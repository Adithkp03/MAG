import json
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import text
from ..models.entities import Product, AgentSession, AgentRun, AgentMessage, AgentToolCall, AuditEvent
from ..services.growth_intelligence import compute_product_metrics, compute_customer_metrics, rank_candidates
from .groq_client import get_groq_client
from ..core.tracing import start_span, end_span

GROWTH_SYSTEM = """You are Growth Agent for Merchant Autonomous Growth. Find evidence-based opportunities for the AUTHENTICATED merchant only. You REASON but never directly mutate financial state — all writes go via Tool Gateway -> Policy -> Canonical.

Tools (all require merchant_id from authenticated context — never invent or guess):
- get_revenue_metrics(merchant_id)
- get_product_metrics(merchant_id): per-product conversion/attach/stock/margin
- find_growth_opportunities(merchant_id): low attach high stock gaps
- get_cross_sell_candidates(category, merchant_id): ranked with affinity evidence
- estimate_campaign(target_category, discount, merchant_id): expected revenue/margin via eligible*conv*price*margin
- get_customer_segments(merchant_id): RFM segments, churn, CLV
- get_product_intelligence(merchant_id): velocity, DIO, attach, demand trend, slow score, inventory_history
- get_merchant_objectives(merchant_id): primary_objective, risk_tolerance, min_margin
- get_opportunities_ranked(merchant_id): scored opps with priority/economics
- get_campaign_history(merchant_id): past campaigns + uplift metrics
- get_inventory_risk(merchant_id): low stock / dead stock evidence
- get_churn_report(merchant_id): churn_prob > threshold with recency evidence
- propose_campaign(opportunity_id, merchant_id): creates PROPOSED campaign via Policy (no direct financial mutation)
- estimate_incrementality(campaign_id, merchant_id): treatment/control 10% holdout uplift

CRITICAL: merchant_id MUST come from authenticated principal. Never invent. Server overrides hallucinated IDs. Use supplied merchant_id.
Workflow: get_revenue_metrics -> get_product_metrics or find_growth_opportunities -> get_customer_segments -> get_cross_sell_candidates -> estimate_campaign -> propose_campaign. Cite numbers. Propose one campaign with reasoning, not direct mutation.
"""

GROWTH_TOOLS = [
    {"type":"function","function":{"name":"get_revenue_metrics","description":"Get merchant revenue metrics","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_product_metrics","description":"Per-product conversion and attach with margin","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"find_growth_opportunities","description":"Find low attach high stock opportunities","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_cross_sell_candidates","description":"Ranked cross-sell with evidence","parameters":{"type":"object","properties":{"category":{"type":"string"},"merchant_id":{"type":"string"}},"required":["category"]}}},
    {"type":"function","function":{"name":"estimate_campaign","description":"Estimate campaign impact","parameters":{"type":"object","properties":{"target_category":{"type":"string"},"discount":{"type":"integer"},"merchant_id":{"type":"string"}},"required":["target_category"]}}},
    {"type":"function","function":{"name":"get_customer_segments","description":"RFM segments, churn, CLV","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_product_intelligence","description":"Velocity, DIO, attach, demand trend, inventory history","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_merchant_objectives","description":"Merchant objectives and risk tolerance","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_opportunities_ranked","description":"Scored opportunities with economics","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_campaign_history","description":"Past campaigns with uplift metrics","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_inventory_risk","description":"Low stock / dead stock risks","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"get_churn_report","description":"Churn report with recency evidence","parameters":{"type":"object","properties":{"merchant_id":{"type":"string"}},"required":["merchant_id"]}}},
    {"type":"function","function":{"name":"propose_campaign","description":"Propose campaign from opportunity (PROPOSED, no direct financial write)","parameters":{"type":"object","properties":{"opportunity_id":{"type":"string"},"merchant_id":{"type":"string"}},"required":["opportunity_id"]}}},
    {"type":"function","function":{"name":"estimate_incrementality","description":"Treatment/control 10% holdout uplift for campaign","parameters":{"type":"object","properties":{"campaign_id":{"type":"string"},"merchant_id":{"type":"string"}},"required":["campaign_id"]}}},
]

def growth_gateway(db: Session, tool: str, args: dict, authenticated_merchant_id: str = None):
    mid = authenticated_merchant_id or args.get("merchant_id")
    if not mid:
        return {"error": "merchant_id required from authenticated context", "policy": {"allowed": False}}
    from ..models.entities import Merchant
    if not db.query(Merchant).filter(Merchant.id==mid).first():
        return {"error": f"unknown merchant {mid}", "policy": {"allowed": False}}
    if tool=="get_revenue_metrics":
        row=db.execute(text("SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev, COALESCE(AVG(total),0) as aov FROM orders WHERE merchant_id=:mid AND status='paid'"), {"mid": mid}).mappings().first()
        return {"output": {"order_count": row["cnt"], "revenue_paise": int(row["rev"]), "revenue_inr": round(float(row["rev"])/100,2), "aov_inr": round(float(row["aov"])/100,2) if row["aov"] else 0}}
    elif tool=="get_product_metrics":
        return {"output": compute_product_metrics(db, mid)}
    elif tool=="find_growth_opportunities":
        opp=db.execute(text("SELECT p.category, COUNT(DISTINCT o.id) as orders, AVG(p.stock) as avg_stock FROM products p LEFT JOIN cart_items ci ON ci.product_id=p.id LEFT JOIN carts c ON ci.cart_id=c.id LEFT JOIN checkouts ch ON ch.cart_id=c.id LEFT JOIN orders o ON o.checkout_id=ch.id WHERE p.merchant_id=:mid GROUP BY p.category"), {"mid": mid}).mappings().all()
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
        data=compute_product_metrics(db, mid)
        base=next((m for m in data["metrics"] if m["category"].lower()==cat.lower()), None)
        if not base:
            return {"output": {"estimated_lift": "unknown", "reason": "no history"}}
        lift_orders = int(base["orders_with_category"] * 0.3)
        avg_price=79900
        incremental = lift_orders * avg_price * (1 - disc/100)
        return {"output": {"target": cat, "discount": disc, "base_orders": base["orders_with_category"], "estimated_incremental_paise": int(incremental), "estimated_incremental_inr": round(incremental/100,2), "reason": f"{lift_orders} incremental adds from {base['orders_with_category']} base orders at {disc}% discount"}}
    elif tool=="get_customer_segments":
        from ..services.autonomous_growth import compute_customer_intelligence
        segs=compute_customer_intelligence(db, mid)
        # aggregate by segment
        from collections import Counter
        counts=Counter(s["segment"] for s in segs)
        return {"output": {"total": len(segs), "by_segment": dict(counts), "sample": segs[:3]}}
    elif tool=="get_product_intelligence":
        from ..services.autonomous_growth import compute_product_intelligence
        intel=compute_product_intelligence(db, mid)
        return {"output": {"count": len(intel), "products": intel[:5]}}
    elif tool=="get_merchant_objectives":
        from ..services.autonomous_growth import ensure_merchant_objective
        obj=ensure_merchant_objective(db, mid)
        return {"output": {"merchant_id": mid, "primary_objective": obj.primary_objective, "risk_tolerance": obj.risk_tolerance, "min_margin_pct": obj.min_margin_pct, "max_campaign_budget": obj.max_campaign_budget, "max_discount": obj.max_discount}}
    elif tool=="get_opportunities_ranked":
        from ..services.autonomous_growth import detect_opportunities, score_opportunities
        detect_opportunities(db, mid)
        scored=score_opportunities(db, mid)
        return {"output": {"count": len(scored), "top": [{"type": o.type, "priority": o.priority, "expected_revenue": o.expected_revenue, "confidence": o.confidence, "evidence": o.evidence} for o in scored[:5]]}}
    elif tool=="get_campaign_history":
        from ..models.entities import Campaign, CampaignMetric
        camps=db.query(Campaign).filter(Campaign.merchant_id==mid).order_by(Campaign.created_at.desc()).limit(5).all()
        out=[]
        for c in camps:
            mets=db.query(CampaignMetric).filter(CampaignMetric.campaign_id==c.id).all()
            out.append({"campaign_id": c.id, "status": c.status, "discount": c.discount, "expected_incremental": c.expected_incremental_paise, "metrics": [{"revenue": m.revenue_paise, "uplift": m.uplift_paise} for m in mets]})
        return {"output": {"campaigns": out}}
    elif tool=="get_inventory_risk":
        from ..services.autonomous_growth import compute_product_intelligence
        intel=compute_product_intelligence(db, mid)
        risks=[p for p in intel if p["doi"]<7 or p["slow_score"]>0.6]
        return {"output": {"risks": risks[:5], "count": len(risks)}}
    elif tool=="get_churn_report":
        from ..services.autonomous_growth import compute_customer_intelligence
        segs=compute_customer_intelligence(db, mid)
        churned=[s for s in segs if s["churn_prob"]>0.5]
        return {"output": {"churned_count": len(churned), "churned": churned[:5]}}
    elif tool=="propose_campaign":
        opp_id=args.get("opportunity_id")
        from ..services.autonomous_growth import plan_action
        res=plan_action(db, opp_id)
        if not res: return {"error": "opportunity not found"}
        # Phase 11: no direct financial mutation — propose only, gated by Policy
        return {"output": {"opportunity_id": opp_id, "campaign_id": res["campaign"].id, "status": res["campaign"].status, "policy": res["policy"], "economics": res["economics"], "note": "PROPOSED via Policy, requires approval if high risk"}}
    elif tool=="estimate_incrementality":
        camp_id=args.get("campaign_id")
        from ..models.entities import CampaignMetric
        mets=db.query(CampaignMetric).filter(CampaignMetric.campaign_id==camp_id).all()
        if not mets: return {"output": {"incrementality": "no metrics yet, 10% holdout will be measured after execute"}}
        total_rev=sum(m.revenue_paise or 0 for m in mets); total_uplift=sum(m.uplift_paise or 0 for m in mets)
        return {"output": {"campaign_id": camp_id, "total_revenue": total_rev, "incremental_revenue": total_uplift, "uplift_pct": round(total_uplift/max(total_rev-total_uplift,1)*100,1) if total_rev else 0}}
    else:
        return {"error": f"unknown {tool}"}

def run_growth_agent(db: Session, merchant_id: str, user_message: str="Find growth opportunities"):
    client=get_groq_client()
    sess=db.query(AgentSession).filter(AgentSession.merchant_id==merchant_id).first()
    if not sess:
        sess=AgentSession(merchant_id=merchant_id); db.add(sess); db.commit(); db.refresh(sess)
    run=AgentRun(session_id=sess.id, merchant_id=merchant_id, user_message=user_message, status="running")
    db.add(run); db.commit(); db.refresh(run)
    db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="user", content=user_message)); db.commit()
    if not client:
        out=growth_gateway(db, "find_growth_opportunities", {"merchant_id": merchant_id}, authenticated_merchant_id=merchant_id)
        run.final_reply=str(out["output"]); run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
        return {"run": run, "tool_calls": [], "fallback": True}
    messages=[{"role":"system","content": GROWTH_SYSTEM}, {"role":"user","content": user_message}]
    tool_log=[]
    for _ in range(6):
        llm_span=start_span("llm.call", attrs={"agent":"growth"})
        resp=client.chat.completions.create(model="openai/gpt-oss-20b", messages=messages, tools=GROWTH_TOOLS, tool_choice="auto", temperature=0.2, max_tokens=900)
        end_span(llm_span, status="ok")
        msg=resp.choices[0].message
        db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="assistant", content=msg.content or "")); db.commit()
        if not msg.tool_calls:
            run.final_reply=msg.content or "Growth analysis complete"; run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
            break
        for tc in msg.tool_calls:
            fname=tc.function.name
            try: args=json.loads(tc.function.arguments or "{}")
            except: args={}
            tspan=start_span(f"tool:{fname}")
            res=growth_gateway(db, fname, args, authenticated_merchant_id=merchant_id)
            end_span(tspan)
            tcr=AgentToolCall(run_id=run.id, session_id=sess.id, tool=fname, input=args, output=res)
            db.add(tcr); db.commit()
            tool_log.append({"tool": fname, "input": args, "output": res})
            messages.append({"role":"assistant","content": msg.content or "", "tool_calls": [{"id": tc.id, "type":"function","function":{"name": fname, "arguments": tc.function.arguments}}]})
            messages.append({"role":"tool","tool_call_id": tc.id, "content": json.dumps(res)[:2000]})
            db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="tool", content=json.dumps(res)[:2000], tool_call_id=tc.id)); db.commit()
    else:
        run.final_reply=f"Completed {len(tool_log)} growth steps"; run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
    return {"run": run, "tool_calls": tool_log}
