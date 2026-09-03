
import json, uuid, time
from datetime import datetime
from sqlalchemy.orm import Session
from ..models.entities import AgentSession, AgentRun, AgentMessage, AgentToolCall, Product, Cart, CartItem, AuditEvent
from ..services.catalog import search_products
from ..services.recommendation import recommend_cross_sell
from ..trust.policy import check_policy
from ..core.events import publish
from .groq_client import get_groq_client
from ..core.tracing import start_trace, start_span, end_span, get_trace_id
from .groq_client import SYSTEM_PROMPT, TOOLS_SCHEMA

def tool_gateway(db: Session, merchant_id: str, tool: str, args: dict, run_id: str = None):
    """Execute tool via gateway: schema + policy + audit. Returns {output, policy, error}"""
    try:
        if tool == "search_products":
            q=args.get("q",""); cat=args.get("category",""); mx=args.get("max_price")
            res = search_products(db, merchant_id, q, cat, mx)
            out = [{"id": p.id, "name": p.name, "price": p.price, "category": p.category, "stock": p.stock} for p in res[:10]]
            return {"output": out, "policy": {"allowed": True}}
        elif tool == "get_product":
            p=db.query(Product).filter(Product.id==args["product_id"]).first()
            if not p: return {"error": "product not found"}
            return {"output": {"id": p.id, "name": p.name, "price": p.price, "category": p.category, "stock": p.stock, "description": p.description}, "policy": {"allowed": True}}
        elif tool == "check_inventory":
            p=db.query(Product).filter(Product.id==args["product_id"]).first()
            if not p: return {"error": "product not found"}
            return {"output": {"product_id": p.id, "stock": p.stock, "available": p.stock>0}, "policy": {"allowed": True}}
        elif tool == "create_cart":
            requested_mid=args.get("merchant_id")
            if requested_mid and requested_mid != merchant_id:
                return {"error": f"merchant_id mismatch: tool requested {requested_mid} but authenticated merchant is {merchant_id} - rejected", "policy": {"allowed": False}, "blocked": True}
            from ..services.commerce import create_cart_svc
            try:
                c=create_cart_svc(db, merchant_id, args.get("customer_id"))
                return {"output": {"cart_id": c.id, "status": c.status}, "policy": {"allowed": True}}
            except Exception as e:
                return {"error": str(e), "policy": {"allowed": False}}
        elif tool == "add_to_cart":
            from ..services.commerce import add_item_svc
            try:
                res=add_item_svc(db, args["cart_id"], args["product_id"], int(args.get("quantity",1)))
                return {"output": res, "policy": res.get("policy", {"allowed": True})}
            except Exception as e:
                # extract HTTPException detail
                msg=str(e.detail) if hasattr(e, "detail") else str(e)
                return {"error": msg, "policy": {"allowed": False}, "blocked": "policy_blocked" in msg}
        elif tool == "get_cart":
            cart=db.query(Cart).filter(Cart.id==args["cart_id"]).first()
            if not cart: return {"error": "cart not found"}
            items=db.query(CartItem).filter(CartItem.cart_id==cart.id).all()
            out_items=[]
            for it in items:
                p=db.query(Product).filter(Product.id==it.product_id).first()
                out_items.append({"product_id": it.product_id, "name": p.name if p else "", "quantity": it.quantity, "line_total": it.line_total})
            return {"output": {"cart_id": cart.id, "status": cart.status, "total": cart.total, "total_inr": cart.total/100 if cart.total else 0, "items": out_items}, "policy": {"allowed": True}}
        elif tool == "request_checkout":
            from ..services.commerce import create_checkout_svc
            try:
                res=create_checkout_svc(db, args["cart_id"])
                chk=res["checkout"]; ord=res.get("order")
                return {"output": {"checkout_id": chk.id, "order_id": ord.id if ord else None, "total": chk.total, "status": chk.status}, "policy": res.get("policy", {"allowed": True})}
            except Exception as e:
                detail=e.detail if hasattr(e, "detail") else str(e)
                # 402 approval_required -> blocked
                if isinstance(detail, dict) and detail.get("code")=="approval_required":
                    return {"error": detail.get("message"), "policy": {"allowed": False, "requires_approval": True, "decision": "escalated"}, "blocked": True, "requires_approval": True, "approval_id": detail.get("approval_id")}
                return {"error": str(detail), "policy": {"allowed": False}}
        else:
            return {"error": f"unknown tool {tool}"}
    except Exception as e:
        return {"error": str(e)}

def run_agent(db: Session, merchant_id: str, customer_id: str, user_message: str, session_id: str = None, model: str = None):
    client=get_groq_client()
    if session_id:
        sess=db.query(AgentSession).filter(AgentSession.id==session_id).first()
    else:
        sess=None
    if not sess:
        sess=AgentSession(merchant_id=merchant_id, customer_id=customer_id)
        db.add(sess); db.commit(); db.refresh(sess)
    run=AgentRun(session_id=sess.id, merchant_id=merchant_id, customer_id=customer_id, user_message=user_message, status="running")
    db.add(run); db.commit(); db.refresh(run)
    db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="user", content=user_message)); db.commit()

    if not client:
        prods=search_products(db, merchant_id, user_message, max_price=None)
        run.status="completed"; run.final_reply=f"[FALLBACK deterministic] found {len(prods)} products, top {prods[0].name if prods else 'none'} - Groq unavailable"; run.termination_reason="fallback"; run.completed_at=datetime.utcnow(); db.commit()
        return {"run": run, "messages": [], "tool_calls": [], "fallback": True, "mode": "fallback"}

    # P0 #9 load recent history (last 3 runs) into context
    messages=[{"role":"system","content": SYSTEM_PROMPT}]
    recent_runs=db.query(AgentRun).filter(AgentRun.session_id==sess.id, AgentRun.id!=run.id).order_by(AgentRun.created_at.desc()).limit(3).all()
    for r in reversed(recent_runs):
        msgs=db.query(AgentMessage).filter(AgentMessage.run_id==r.id).order_by(AgentMessage.created_at).all()
        for m in msgs[-4:]:  # last 4 per run to keep context small
            if m.role in ("user","assistant"):
                messages.append({"role": m.role, "content": m.content[:800]})
    messages.append({"role":"user","content": user_message})

    tool_calls_log=[]
    max_steps=6
    termination_reason="completed"
    for step in range(max_steps):
        llm_span=start_span("llm.call", attrs={"model": model or "openai/gpt-oss-20b"})
        resp=client.chat.completions.create(model=model or "openai/gpt-oss-20b", messages=messages, tools=TOOLS_SCHEMA, tool_choice="auto", temperature=0.2, max_tokens=800)
        end_span(llm_span, status="ok", attrs={"has_tool_calls": bool(resp.choices[0].message.tool_calls)})
        msg=resp.choices[0].message
        db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="assistant", content=msg.content or "")); db.commit()
        if not msg.tool_calls:
            run.final_reply=msg.content or "Completed"
            termination_reason="completed"
            run.status="completed"; run.termination_reason=termination_reason; run.completed_at=datetime.utcnow(); db.commit()
            break
        for tc in msg.tool_calls:
            fname=tc.function.name
            try: args=json.loads(tc.function.arguments or "{}")
            except: args={}
            tspan=start_span(f"tool:{fname}", attrs={"tool": fname})
            result=tool_gateway(db, merchant_id, fname, args, run.id)
            end_span(tspan, status="error" if result.get("error") else "ok")
            tcr=AgentToolCall(run_id=run.id, session_id=sess.id, tool=fname, input=args, output=result, policy_result=str(result.get("policy",{}).get("decision","")), risk_score=result.get("policy",{}).get("risk"))
            db.add(tcr); db.commit()
            tool_calls_log.append({"tool": fname, "input": args, "output": result})
            tool_msg={"role":"tool","tool_call_id": tc.id, "content": json.dumps(result)[:2000]}
            messages.append({"role":"assistant","content": msg.content or "", "tool_calls": [{"id": tc.id, "type":"function","function":{"name": fname, "arguments": tc.function.arguments}}]})
            messages.append(tool_msg)
            db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="tool", content=json.dumps(result)[:2000], tool_call_id=tc.id)); db.commit()
            if result.get("blocked"):
                run.status="blocked"; run.termination_reason="needs_approval"; run.final_reply=f"Blocked by policy: {result.get('error')}" ; run.completed_at=datetime.utcnow(); db.commit()
                return {"run": run, "tool_calls": tool_calls_log, "messages": messages, "mode": "agent"}
        # continue loop
    else:
        # P0 #8 did not complete within max_steps
        termination_reason="max_steps_exceeded"
        run.final_reply = f"Stopped after {max_steps} tool steps - task incomplete (max_steps_exceeded). Last: {tool_calls_log[-1]['tool'] if tool_calls_log else 'none'}"
        run.status="failed"; run.termination_reason=termination_reason; run.completed_at=datetime.utcnow(); db.commit()
    if not run.final_reply:
        run.final_reply = "Completed workflow"
        db.commit()
    return {"run": run, "tool_calls": tool_calls_log, "messages": messages, "termination_reason": termination_reason, "mode": "agent"}
