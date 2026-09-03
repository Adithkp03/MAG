from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Cart, Checkout, Order, Payment, AuditEvent
from ...trust.policy import check_policy
from ...core.events import publish
import uuid

router = APIRouter(prefix="/checkout", tags=["checkout"])

@router.post("")
def create_checkout(payload: dict, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    cart_id = payload["cart_id"]
    cart = db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: return {"error":"cart not found"}
    if cart.status != "active": return {"error": f"cart {cart.status}"}
    # idempotency by cart
    existing = db.query(Checkout).filter(Checkout.cart_id==cart_id).first()
    if existing: return existing
    if not idempotency_key: idempotency_key = f"chk_{uuid.uuid4().hex[:10]}"
    # policy FINANCIAL
    pol = check_policy(db, cart.merchant_id, "create_payment", amount=cart.total)
    if not pol["allowed"]:
        # create blocked checkout for audit + human approval flow
        chk_blocked = Checkout(cart_id=cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="blocked", idempotency_key=idempotency_key)
        db.add(chk_blocked)
        ae = AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="blocked" if pol["decision"]=="blocked" else "escalated", result=pol["decision"], reason=pol["reason"], payload={"cart_id": cart_id})
        db.add(ae); db.commit(); db.refresh(chk_blocked)
        return {"error": pol["reason"], "decision": pol["decision"], "requires_approval": pol["requires_approval"], "policy": pol, "checkout": chk_blocked}
    chk = Checkout(cart_id=cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="validated", idempotency_key=idempotency_key)
    db.add(chk)
    # audit success
    ae = AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id": cart_id})
    db.add(ae); db.commit(); db.refresh(chk)
    cart.status = "checked_out"
    db.commit()
    publish("checkout.created", {"checkout_id": chk.id, "cart_id": cart_id, "total": cart.total})
    # auto-create order in pending
    order = Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
    db.add(order); db.commit(); db.refresh(order)
    publish("order.created", {"order_id": order.id, "checkout_id": chk.id})
    return {"checkout": chk, "order": order, "policy": pol}

@router.get("/{checkout_id}")
def get_checkout(checkout_id: str, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: return {"error":"not found"}
    return chk

@router.post("/{checkout_id}/approve")
def approve(checkout_id: str, payload: dict = {}, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: return {"error":"not found"}
    # human approval overrides policy - create order if missing
    if chk.status == "blocked":
        chk.status = "validated"
        db.commit()
        order = db.query(Order).filter(Order.checkout_id==checkout_id).first()
        if not order:
            order = Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
            db.add(order)
        ae = AuditEvent(merchant_id=chk.merchant_id, action="approve_checkout", amount=chk.total, policy_result="overridden", authorization="human_approved", result="approved", reason=payload.get("reason","human approval"), payload={"checkout_id": checkout_id})
        db.add(ae); db.commit()
        return {"checkout": chk, "order": order, "approved": True}
    return {"checkout": chk, "note": f"status {chk.status} not blocked, no approval needed"}

@router.post("/{checkout_id}/cancel")
def cancel(checkout_id: str, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: return {"error":"not found"}
    chk.status="cancelled"
    db.commit()
    return chk

@router.post("/{checkout_id}/complete")
async def complete(checkout_id: str, payload: dict = {}, db: Session = Depends(get_db)):
    from ...services.razorpay_adapter import create_razorpay_order, has_keys
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: return {"error":"not found"}
    if chk.status in ("cancelled","captured"): return {"error": f"already {chk.status}"}
    if chk.status == "blocked": return {"error":"checkout blocked - requires approval via POST /checkout/{id}/approve", "status": chk.status}
    chk.status="payment_pending"
    db.commit()
    order = db.query(Order).filter(Order.checkout_id==checkout_id).first()
    rzp = await create_razorpay_order(chk.total, f"rcpt_{checkout_id}"[:40], notes={"checkout_id": checkout_id, "merchant_id": chk.merchant_id})
    pay = Payment(order_id=order.id if order else None, merchant_id=chk.merchant_id, amount=chk.total, status="pending", razorpay_order_id=rzp.get("id"), idempotency_key=f"pay_{uuid.uuid4().hex[:8]}")
    db.add(pay); db.commit(); db.refresh(pay)
    if order:
        order.payment_id = pay.id; db.commit()
    ae = AuditEvent(merchant_id=chk.merchant_id, action="create_payment", amount=chk.total, policy_result="approved", authorization="approved", result="pending", reason=f"payment initiated razorpay_order={rzp.get('id')} live={has_keys()}", payload={"checkout_id": checkout_id, "payment_id": pay.id, "razorpay_order_id": rzp.get("id")})
    db.add(ae); db.commit()
    publish("payment.created", {"payment_id": pay.id, "checkout_id": checkout_id, "razorpay_order_id": rzp.get("id")})
    return {"checkout": chk, "payment": pay, "order": order, "razorpay_order": rzp, "has_live_keys": has_keys()}
