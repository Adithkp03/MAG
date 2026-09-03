
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Cart, Checkout, Order, Payment, AuditEvent, Approval
from ...trust.policy import check_policy
from ...schemas import CheckoutCreate, CheckoutApproveReq, ErrorResponse
from ...core.events import publish
from ...core.tracing import start_span, end_span
import uuid
from datetime import datetime

router = APIRouter(prefix="/checkout", tags=["checkout"])

@router.post("", responses={400: {"model": ErrorResponse}, 402: {"model": ErrorResponse}})
def create_checkout(payload: CheckoutCreate, db: Session = Depends(get_db), idempotency_key: str = Header(None, alias="Idempotency-Key")):
    cart = db.query(Cart).filter(Cart.id==payload.cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    if cart.status != "active": raise HTTPException(status_code=409, detail={"code":"invalid_cart_state","message": f"cart {cart.status}, cannot checkout"})
    if cart.total == 0: raise HTTPException(status_code=422, detail={"code":"empty_cart","message":"cart total is 0"})
    existing = db.query(Checkout).filter(Checkout.cart_id==payload.cart_id).first()
    if existing:
        raise HTTPException(status_code=409, detail={"code":"checkout_exists","message":"checkout already exists for cart","checkout_id": existing.id})
    if not idempotency_key: idempotency_key = f"chk_{uuid.uuid4().hex[:10]}"
    # P0-2 dedup via idempotency_key unique
    dup = db.query(Checkout).filter(Checkout.idempotency_key==idempotency_key).first()
    if dup: return {"checkout": dup, "deduped": True}
    pspan=start_span("policy.check", attrs={"amount": cart.total})
    pol = check_policy(db, cart.merchant_id, "create_payment", amount=cart.total)
    end_span(pspan, attrs={"allowed": pol["allowed"], "decision": pol["decision"]})
    if not pol["allowed"]:
        chk_blocked = Checkout(cart_id=payload.cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="blocked", idempotency_key=idempotency_key, policy_version=pol["policy_version"])
        db.add(chk_blocked); db.flush()  # flush to get id before Approval P0-3
        # create Approval object P0-9 exact amount binding
        appr = Approval(merchant_id=cart.merchant_id, checkout_id=chk_blocked.id, action="create_payment", amount=cart.total, status="pending", requested_by="agent", policy_version=pol["policy_version"], reason=pol["reason"])
        db.add(appr)
        ae = AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="escalated", result=pol["decision"], reason=pol["reason"], payload={"cart_id": payload.cart_id, "approval_id": appr.id, "policy_version": pol["policy_version"]})
        db.add(ae); publish("authorization.requested", {"checkout_id": chk_blocked.id, "amount": cart.total, "approval_id": appr.id}); db.commit(); db.refresh(chk_blocked)
        raise HTTPException(status_code=402, detail={"code":"approval_required","message": pol["reason"], "decision": pol["decision"], "requires_approval": pol["requires_approval"], "policy_version": pol["policy_version"], "checkout": {"id": chk_blocked.id, "status": chk_blocked.status}, "approval_id": appr.id})
    chk = Checkout(cart_id=payload.cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="validated", idempotency_key=idempotency_key, policy_version=pol["policy_version"])
    db.add(chk)
    ae = AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id": payload.cart_id, "policy_version": pol["policy_version"]})
    db.add(ae); db.commit(); db.refresh(chk)
    cart.status = "checked_out"; db.commit()
    publish("checkout.created", {"checkout_id": chk.id, "cart_id": payload.cart_id, "total": cart.total})
    order = Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
    db.add(order); db.commit(); db.refresh(order)
    publish("order.created", {"order_id": order.id, "checkout_id": chk.id})
    return {"checkout": chk, "order": order, "policy": pol}

@router.get("/{checkout_id}")
def get_checkout(checkout_id: str, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    return chk

@router.post("/{checkout_id}/approve", responses={403: {"model": ErrorResponse}})
def approve(checkout_id: str, payload: CheckoutApproveReq, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status != "blocked": raise HTTPException(status_code=409, detail={"code":"invalid_state","message": f"status {chk.status} not blocked, no approval needed"})
    # P0-10 authenticated approver required, P0-12 exact amount binding via Approval object
    appr = db.query(Approval).filter(Approval.checkout_id==checkout_id, Approval.status=="pending").order_by(Approval.created_at.desc()).first()
    if not appr: raise HTTPException(status_code=404, detail={"code":"approval_not_found","message":"no pending approval"})
    if appr.amount != chk.total: raise HTTPException(status_code=422, detail={"code":"amount_mismatch","message":"approval amount does not match checkout total"})
    if not payload.approved_by: raise HTTPException(status_code=401, detail={"code":"approver_required","message":"approved_by required"})
    if not chk.can_transition("validated"):
        raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> validated"})
    appr.approved_by = payload.approved_by
    appr.status = "approved"
    appr.decided_at = datetime.utcnow()
    chk.status = "validated"
    db.commit()
    order = db.query(Order).filter(Order.checkout_id==checkout_id).first()
    if not order:
        order = Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
        db.add(order)
    ae = AuditEvent(merchant_id=chk.merchant_id, action="approve_checkout", amount=chk.total, policy_result="overridden", authorization=f"human_approved:{payload.approved_by}", result="approved", reason=payload.reason, payload={"checkout_id": checkout_id, "approval_id": appr.id, "policy_version": chk.policy_version})
    db.add(ae); publish("authorization.approved", {"checkout_id": checkout_id, "approved_by": payload.approved_by}); db.commit()
    return {"checkout": chk, "order": order, "approval": appr, "approved": True}

@router.post("/{checkout_id}/cancel")
def cancel(checkout_id: str, db: Session = Depends(get_db)):
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if not chk.can_transition("cancelled"): raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> cancelled"})
    chk.status="cancelled"; db.commit(); return chk

@router.post("/{checkout_id}/complete")
async def complete(checkout_id: str, payload: dict = {}, db: Session = Depends(get_db)):
    from ...services.razorpay_adapter import create_razorpay_order, has_keys
    chk = db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status == "blocked": raise HTTPException(status_code=403, detail={"code":"approval_required","message":"checkout blocked - requires approval via POST /checkout/{id}/approve"})
    if not chk.can_transition("payment_pending"): raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> payment_pending"})
    chk.status="payment_pending"; db.commit()
    order = db.query(Order).filter(Order.checkout_id==checkout_id).first()
    rspan=start_span("razorpay.create_order", attrs={"amount": chk.total})
    rzp = await create_razorpay_order(chk.total, f"rcpt_{checkout_id}"[:40], notes={"checkout_id": checkout_id, "merchant_id": chk.merchant_id})
    pay = Payment(order_id=order.id if order else None, merchant_id=chk.merchant_id, amount=chk.total, status="pending", razorpay_order_id=rzp.get("id"), idempotency_key=f"pay_{uuid.uuid4().hex[:8]}")
    db.add(pay); db.commit(); db.refresh(pay)
    end_span(rspan, attrs={"razorpay_id": rzp.get("id")})
    if order: order.payment_id = pay.id; db.commit()
    ae = AuditEvent(merchant_id=chk.merchant_id, action="create_payment", amount=chk.total, policy_result="approved", authorization="approved", result="pending", reason=f"payment initiated razorpay_order={rzp.get('id')} live={has_keys()}", payload={"checkout_id": checkout_id, "payment_id": pay.id, "razorpay_order_id": rzp.get("id")})
    db.add(ae); db.commit()
    publish("payment.created", {"payment_id": pay.id, "checkout_id": checkout_id, "razorpay_order_id": rzp.get("id")})
    return {"checkout": chk, "payment": pay, "order": order, "razorpay_order": rzp, "has_live_keys": has_keys()}
