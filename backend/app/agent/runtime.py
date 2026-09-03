
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

# Map tool names to executors with Trust gateway P0-12 exact binding
def tool_gateway(db: Session, merchant_id: str, tool: str, args: dict, run_id: str = None):
    """Execute tool via gateway: schema + policy + audit. Returns {output, policy, error}"""
    try:
        if tool == "search_products":
            q=args.get("q",""); cat=args.get("category",""); mx=args.get("max_price")
            res = search_products(db, merchant_id, q, cat, mx)
            # convert to serializable
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
            # validate merchant_id, fallback to session merchant_id if hallucinated
            mid=args.get("merchant_id", merchant_id) or merchant_id
            # check exists
            from ..models.entities import Merchant
            if not db.query(Merchant).filter(Merchant.id==mid).first():
                mid=merchant_id
            c=Cart(merchant_id=mid, customer_id=args.get("customer_id"))
            try:
                db.add(c); db.commit(); db.refresh(c)
            except Exception as e:
                db.rollback()
                return {"error": f"create_cart failed: {e}", "policy": {"allowed": False}}
            publish("cart.created", {"cart_id": c.id})
            ae=AuditEvent(merchant_id=merchant_id, action="agent_create_cart", amount=0, policy_result="approved", authorization="approved", result="success", reason="agent tool", payload={"cart_id": c.id, "run_id": run_id})
            db.add(ae); db.commit()
            return {"output": {"cart_id": c.id, "status": c.status}, "policy": {"allowed": True}}
        elif tool == "add_to_cart":
            cart=db.query(Cart).filter(Cart.id==args["cart_id"]).first()
            if not cart: return {"error": "cart not found"}
            prod=db.query(Product).filter(Product.id==args["product_id"]).first()
            if not prod: return {"error": "product not found"}
            qty=int(args.get("quantity",1))
            line=prod.price*qty
            pol=check_policy(db, merchant_id, "add_item", amount=(cart.total or 0)+line)
            if not pol["allowed"]:
                ae=AuditEvent(merchant_id=merchant_id, action="agent_add_item", amount=line, policy_result=pol["decision"], authorization="blocked", result="blocked", reason=pol["reason"], payload={"cart_id": cart.id, "product_id": prod.id, "run_id": run_id, "policy_version": pol["policy_version"]})
                db.add(ae); db.commit()
                return {"error": pol["reason"], "policy": pol, "blocked": True}
            # add
            existing=db.query(CartItem).filter(CartItem.cart_id==cart.id, CartItem.product_id==prod.id).first()
            if existing:
                existing.quantity+=qty; existing.line_total+=line
            else:
                ci=CartItem(cart_id=cart.id, product_id=prod.id, quantity=qty, unit_price=prod.price, line_total=line)
                db.add(ci)
            cart.total=(cart.total or 0)+line
            ae=AuditEvent(merchant_id=merchant_id, action="agent_add_item", amount=line, policy_result="approved", authorization="approved", result="success", reason=pol["reason"], payload={"cart_id": cart.id, "product_id": prod.id, "run_id": run_id})
            db.add(ae); db.commit(); db.refresh(cart)
            publish("cart.item_added", {"cart_id": cart.id, "product_id": prod.id})
            return {"output": {"cart_id": cart.id, "total": cart.total, "added": prod.name, "total_inr": cart.total/100}, "policy": pol}
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
            # create checkout via internal logic with trust check
            from ..models.entities import Checkout, Order
            cart=db.query(Cart).filter(Cart.id==args["cart_id"]).first()
            if not cart: return {"error": "cart not found"}
            pol=check_policy(db, merchant_id, "create_payment", amount=cart.total or 0)
            if not pol["allowed"]:
                return {"error": pol["reason"], "policy": pol, "blocked": True, "requires_approval": pol["requires_approval"]}
            # mimic checkout create
            import uuid
            chk=__import__("backend.app.models.entities", fromlist=["Checkout"]).Checkout(cart_id=cart.id, merchant_id=merchant_id, customer_id=cart.customer_id, total=cart.total, status="validated", idempotency_key=f"chk_{uuid.uuid4().hex[:8]}", policy_version=pol["policy_version"])
            db.add(chk); db.commit(); db.refresh(chk)
            cart.status="checked_out"; db.commit()
            ord=__import__("backend.app.models.entities", fromlist=["Order"]).Order(checkout_id=chk.id, merchant_id=merchant_id, customer_id=cart.customer_id, total=cart.total, status="pending")
            db.add(ord); db.commit(); db.refresh(ord)
            publish("checkout.created", {"checkout_id": chk.id})
            ae=AuditEvent(merchant_id=merchant_id, action="agent_request_checkout", amount=cart.total, policy_result="approved", authorization="approved", result="success", reason=pol["reason"], payload={"cart_id": cart.id, "checkout_id": chk.id, "run_id": run_id})
            db.add(ae); db.commit()
            return {"output": {"checkout_id": chk.id, "order_id": ord.id, "total": chk.total, "status": chk.status}, "policy": pol}
        else:
            return {"error": f"unknown tool {tool}"}
    except Exception as e:
        return {"error": str(e)}

def run_agent(db: Session, merchant_id: str, customer_id: str, user_message: str, session_id: str = None, model: str = None):
    client=get_groq_client()
    # ensure session
    if session_id:
        sess=db.query(AgentSession).filter(AgentSession.id==session_id).first()
    else:
        sess=None
    if not sess:
        sess=AgentSession(merchant_id=merchant_id, customer_id=customer_id)
        db.add(sess); db.commit(); db.refresh(sess)
    run=AgentRun(session_id=sess.id, merchant_id=merchant_id, customer_id=customer_id, user_message=user_message, status="running")
    db.add(run); db.commit(); db.refresh(run)
    # store user message
    db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="user", content=user_message)); db.commit()

    if not client:
        # fallback deterministic 2-step
        prods=search_products(db, merchant_id, user_message, max_price=None)
        recs=recommend_cross_sell(prods[0].category if prods else "keyboard", db.query(Product).all())
        run.status="completed"; run.final_reply=f"Fallback: found {len(prods)} products, top {prods[0].name if prods else 'none'}" ; run.completed_at=datetime.utcnow(); db.commit()
        return {"run": run, "messages": [], "tool_calls": [], "fallback": True}

    messages=[{"role":"system","content": SYSTEM_PROMPT}, {"role":"user","content": user_message}]
    # load recent history (last 3 runs) for memory
    tool_calls_log=[]
    max_steps=6
    for step in range(max_steps):
        llm_span=start_span("llm.call", attrs={"model": model or "openai/gpt-oss-20b"})
        resp=client.chat.completions.create(model=model or "openai/gpt-oss-20b", messages=messages, tools=TOOLS_SCHEMA, tool_choice="auto", temperature=0.2, max_tokens=800)
        end_span(llm_span, status="ok", attrs={"has_tool_calls": bool(resp.choices[0].message.tool_calls)})
        msg=resp.choices[0].message
        # store assistant message
        db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="assistant", content=msg.content or "")); db.commit()
        if not msg.tool_calls:
            run.final_reply=msg.content or "Completed"
            run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
            break
        # execute each tool call (usually 1)
        for tc in msg.tool_calls:
            fname=tc.function.name
            try: args=json.loads(tc.function.arguments or "{}")
            except: args={}
            tspan=start_span(f"tool:{fname}", attrs={"tool": fname})
            result=tool_gateway(db, merchant_id, fname, args, run.id)
            end_span(tspan, status="error" if result.get("error") else "ok")
            # record tool call
            tcr=AgentToolCall(run_id=run.id, session_id=sess.id, tool=fname, input=args, output=result, policy_result=str(result.get("policy",{}).get("decision","")), risk_score=result.get("policy",{}).get("risk"))
            db.add(tcr); db.commit()
            tool_calls_log.append({"tool": fname, "input": args, "output": result})
            # store tool message for LLM
            tool_msg={"role":"tool","tool_call_id": tc.id, "content": json.dumps(result)[:2000]}
            messages.append({"role":"assistant","content": msg.content or "", "tool_calls": [{"id": tc.id, "type":"function","function":{"name": fname, "arguments": tc.function.arguments}}]})
            messages.append(tool_msg)
            db.add(AgentMessage(run_id=run.id, session_id=sess.id, role="tool", content=json.dumps(result)[:2000], tool_call_id=tc.id)); db.commit()
            # if blocked by policy, stop and return
            if result.get("blocked"):
                run.status="blocked"; run.final_reply=f"Blocked by policy: {result.get('error')}" ; run.completed_at=datetime.utcnow(); db.commit()
                return {"run": run, "tool_calls": tool_calls_log, "messages": messages}
        # continue loop
    else:
        run.final_reply = f"Completed {len(tool_calls_log)} tool steps. Last: {tool_calls_log[-1]['tool'] if tool_calls_log else 'none'}"
        run.status="completed"; run.completed_at=datetime.utcnow(); db.commit()
    if not run.final_reply:
        run.final_reply = "Completed workflow"
        db.commit()
    return {"run": run, "tool_calls": tool_calls_log, "messages": messages}
