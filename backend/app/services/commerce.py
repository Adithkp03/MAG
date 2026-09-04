
"""Canonical Commerce Services - single source of truth for REST + Agent + UCP"""
from sqlalchemy.orm import Session
from .inventory import reserve_stock
from .outbox import publish_outbox
from sqlalchemy import text
from fastapi import HTTPException
import uuid
from ..models.entities import Cart, CartItem, Product, Checkout, Order, Payment, AuditEvent, Approval
from ..trust.policy import check_policy
from ..core.events import publish

def create_cart_svc(db: Session, merchant_id: str, customer_id: str=None) -> Cart:
    c=Cart(merchant_id=merchant_id, customer_id=customer_id)
    db.add(c); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(c)
    cid=c.id
    publish("cart.created", {"cart_id": cid, "merchant_id": merchant_id})
    ae=AuditEvent(merchant_id=merchant_id, action="create_cart", amount=0, policy_result="approved", authorization="approved", result="success", reason="canonical", payload={"cart_id": cid})
    db.add(ae); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(c)
    return c

def add_item_svc(db: Session, cart_id: str, product_id: str, quantity: int=1, idempotency_key: str=None) -> dict:
    cart=db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    if cart.status != "active": raise HTTPException(status_code=409, detail={"code":"invalid_cart_state","message":f"cart {cart.status}"})
    prod=db.query(Product).filter(Product.id==product_id).first()
    if not prod: raise HTTPException(status_code=404, detail={"code":"product_not_found","message":"product not found"})
    if prod.stock < quantity: raise HTTPException(status_code=409, detail={"code":"insufficient_stock","message":"insufficient stock"})
    line_total=prod.price*quantity
    pol=check_policy(db, cart.merchant_id, "add_item", amount=cart.total+line_total)
    # allow escalated at cart level, only hard block rejects (defer to checkout)
    if not pol["allowed"] and not pol.get("requires_approval"):
        ae=AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="blocked", result="blocked", reason=pol["reason"], payload={"cart_id":cart_id, "product_id":product_id, "policy_version":pol["policy_version"]})
        db.add(ae); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
        raise HTTPException(status_code=403, detail={"code":"policy_blocked","message":pol["reason"],"decision":pol["decision"],"requires_approval":pol["requires_approval"],"policy_version":pol["policy_version"]})
    existing=db.query(CartItem).filter(CartItem.cart_id==cart_id, CartItem.product_id==product_id).first()
    if existing:
        existing.quantity+=quantity; existing.line_total+=line_total
    else:
        ci=CartItem(cart_id=cart_id, product_id=product_id, quantity=quantity, unit_price=prod.price, line_total=line_total)
        db.add(ci)
    cart.total=(cart.total or 0)+line_total
    ae=AuditEvent(merchant_id=cart.merchant_id, action="add_item", amount=line_total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id":cart_id, "product_id":product_id, "qty":quantity, "policy_version":pol["policy_version"]})
    db.add(ae); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    publish("cart.item_added", {"cart_id":cart_id, "product_id":product_id, "qty":quantity})
    db.refresh(cart)
    return {"cart_id":cart_id, "total":cart.total, "added":prod.name, "policy":pol}

def get_cart_svc(db: Session, cart_id: str) -> dict:
    cart=db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    items=db.query(CartItem).filter(CartItem.cart_id==cart_id).all()
    detailed=[]
    for it in items:
        prod=db.query(Product).filter(Product.id==it.product_id).first()
        detailed.append({"item":it, "product":prod})
    return {"cart":cart, "items":detailed, "total":cart.total}

def create_checkout_svc(db: Session, cart_id: str, idempotency_key: str=None) -> dict:
    cart=db.query(Cart).filter(Cart.id==cart_id).first()
    if not cart: raise HTTPException(status_code=404, detail={"code":"cart_not_found","message":"cart not found"})
    if cart.status != "active": raise HTTPException(status_code=409, detail={"code":"invalid_cart_state","message":f"cart {cart.status}, cannot checkout"})
    if cart.total == 0: raise HTTPException(status_code=422, detail={"code":"empty_cart","message":"cart total is 0"})
    existing=db.query(Checkout).filter(Checkout.cart_id==cart_id).first()
    if existing: raise HTTPException(status_code=409, detail={"code":"checkout_exists","message":"checkout already exists for cart","checkout_id":existing.id})
    if not idempotency_key: idempotency_key=f"chk_{uuid.uuid4().hex[:10]}"
    dup=db.query(Checkout).filter(Checkout.idempotency_key==idempotency_key).first()
    if dup: return {"checkout":dup, "deduped":True}
    pol=check_policy(db, cart.merchant_id, "create_payment", amount=cart.total)
    if not pol["allowed"]:
        chk_blocked=Checkout(cart_id=cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="blocked", idempotency_key=idempotency_key, policy_version=pol["policy_version"])
        db.add(chk_blocked); db.flush()
        from datetime import datetime
        appr=Approval(merchant_id=cart.merchant_id, checkout_id=chk_blocked.id, action="create_payment", amount=cart.total, status="pending", requested_by="commerce", policy_version=pol["policy_version"], reason=pol["reason"])
        db.add(appr)
        ae=AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result=pol["decision"], risk_score=pol["risk"], authorization="escalated", result=pol["decision"], reason=pol["reason"], payload={"cart_id":cart_id, "approval_id":appr.id, "policy_version":pol["policy_version"]})
        db.add(ae); publish("authorization.requested", {"checkout_id":chk_blocked.id, "amount":cart.total, "approval_id":appr.id}); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(chk_blocked)
        raise HTTPException(status_code=402, detail={"code":"approval_required","message":pol["reason"],"decision":pol["decision"],"requires_approval":pol["requires_approval"],"policy_version":pol["policy_version"],"checkout":{"id":chk_blocked.id,"status":chk_blocked.status},"approval_id":appr.id})
    chk=Checkout(cart_id=cart_id, merchant_id=cart.merchant_id, customer_id=cart.customer_id, total=cart.total, status="validated", idempotency_key=idempotency_key, policy_version=pol["policy_version"])
    db.add(chk)
    ae=AuditEvent(merchant_id=cart.merchant_id, action="create_checkout", amount=cart.total, policy_result="approved", risk_score=pol["risk"], authorization="approved", result="success", reason=pol["reason"], payload={"cart_id":cart_id, "policy_version":pol["policy_version"]})
    db.add(ae); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(chk)
    cart.status="checked_out"; db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    publish("checkout.created", {"checkout_id":chk.id, "cart_id":cart_id, "total":cart.total})
    order=Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
    db.add(order); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(order)
    publish("order.created", {"order_id":order.id, "checkout_id":chk.id})
    return {"checkout":chk, "order":order, "policy":pol}

def approve_checkout_svc(db: Session, checkout_id: str, approved_by: str, reason: str=None) -> dict:
    from datetime import datetime
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status != "blocked": raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"status {chk.status} not blocked"})
    appr=db.query(Approval).filter(Approval.checkout_id==checkout_id, Approval.status=="pending").order_by(Approval.created_at.desc()).first()
    if not appr: raise HTTPException(status_code=404, detail={"code":"approval_not_found","message":"no pending approval"})
    if appr.amount != chk.total: raise HTTPException(status_code=422, detail={"code":"amount_mismatch","message":"approval amount does not match checkout total"})
    if not approved_by: raise HTTPException(status_code=401, detail={"code":"approver_required","message":"X-Approved-By header required"})
    if not chk.can_transition("validated"): raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message":f"cannot transition {chk.status} -> validated"})
    appr.approved_by=approved_by; appr.status="approved"; appr.decided_at=datetime.utcnow()
    chk.status="validated"; db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    order=db.query(Order).filter(Order.checkout_id==checkout_id).first()
    if not order:
        order=Order(checkout_id=chk.id, merchant_id=chk.merchant_id, customer_id=chk.customer_id, total=chk.total, status="pending")
        db.add(order)
    ae=AuditEvent(merchant_id=chk.merchant_id, action="approve_checkout", amount=chk.total, policy_result="overridden", authorization=f"human_approved:{approved_by}", result="approved", reason=reason, payload={"checkout_id":checkout_id, "approval_id":appr.id, "policy_version":chk.policy_version})
    db.add(ae); publish("authorization.approved", {"checkout_id":checkout_id, "approved_by":approved_by}); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    return {"checkout":chk, "order":order, "approval":appr, "approved":True}

async def complete_checkout_svc(db: Session, checkout_id: str) -> dict:
    from ..services.razorpay_adapter import create_razorpay_order, has_keys
    from ..core.tracing import start_span, end_span
    chk=db.query(Checkout).filter(Checkout.id==checkout_id).first()
    if not chk: raise HTTPException(status_code=404, detail={"code":"checkout_not_found","message":"not found"})
    if chk.status == "blocked": raise HTTPException(status_code=403, detail={"code":"approval_required","message":"checkout blocked - requires approval via POST /checkout/{id}/approve"})
    if chk.status == "payment_pending":
        # crash recovery: return existing payment
        existing_pay=db.query(Payment).filter(Payment.idempotency_key==f"pay_{checkout_id}").first()
        if existing_pay:
            return {"checkout":chk, "payment":existing_pay, "order":db.query(Order).filter(Order.checkout_id==checkout_id).first(), "razorpay_order":{"id":existing_pay.razorpay_order_id}, "has_live_keys":has_keys(), "deduped":True}
        ord_tmp=db.query(Order).filter(Order.checkout_id==checkout_id).first()
        if ord_tmp:
            ep=db.query(Payment).filter(Payment.order_id==ord_tmp.id).first()
            if ep: return {"checkout":chk, "payment":ep, "order":ord_tmp, "razorpay_order":{"id":ep.razorpay_order_id}, "has_live_keys":has_keys(), "deduped":True}
    if not chk.can_transition("payment_pending"): raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message":f"cannot transition {chk.status} -> payment_pending"})
    deterministic_key=f"pay_{checkout_id}"
    dup_pay=db.query(Payment).filter(Payment.idempotency_key==deterministic_key).first()
    if dup_pay:
        if chk.status != "payment_pending":
            chk.status="payment_pending"; db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
        return {"checkout":chk, "payment":dup_pay, "order":db.query(Order).filter(Order.checkout_id==checkout_id).first(), "razorpay_order":{"id":dup_pay.razorpay_order_id}, "has_live_keys":has_keys(), "deduped":True}
    chk.status="payment_pending"; db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    order=db.query(Order).filter(Order.checkout_id==checkout_id).first()
    rspan=start_span("razorpay.create_order", attrs={"amount":chk.total})
    rzp=await create_razorpay_order(chk.total, f"rcpt_{checkout_id}"[:40], notes={"checkout_id":checkout_id, "merchant_id":chk.merchant_id})
    pay=Payment(order_id=order.id if order else None, merchant_id=chk.merchant_id, amount=chk.total, status="pending", razorpay_order_id=rzp.get("id"), idempotency_key=deterministic_key)
    db.add(pay); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass; db.refresh(pay)
    end_span(rspan, attrs={"razorpay_id":rzp.get("id")})
    if order: order.payment_id=pay.id; db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    ae=AuditEvent(merchant_id=chk.merchant_id, action="create_payment", amount=chk.total, policy_result="approved", authorization="approved", result="pending", reason=f"payment initiated razorpay_order={rzp.get('id')} live={has_keys()} key={deterministic_key}", payload={"checkout_id":checkout_id, "payment_id":pay.id, "razorpay_order_id":rzp.get("id")})
    db.add(ae); db.commit()
    # P2-25 reserve inventory on add
    try:
        reserve_stock(db, product_id, quantity)
    except Exception:
        pass
    publish("payment.created", {"payment_id":pay.id, "checkout_id":checkout_id, "razorpay_order_id":rzp.get("id")})
    return {"checkout":chk, "payment":pay, "order":order, "razorpay_order":rzp, "has_live_keys":has_keys()}
