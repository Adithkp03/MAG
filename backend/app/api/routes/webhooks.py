
from fastapi import APIRouter, Request, Depends, Header
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Payment, Order, Checkout, AuditEvent
from ...core.events import publish
from ...services.razorpay_adapter import verify_webhook_signature
import hmac, hashlib, json

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# dedup in-memory for dev (use Redis set in prod)
_seen=set()

@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature","")
    # Phase 2: real signature verification (allows empty secret in dev)
    if not verify_webhook_signature(body, sig):
        return {"status":"signature_verification_failed", "error":"invalid HMAC"}
    try:
        payload = json.loads(body) if body else {}
    except:
        payload = {}
    event_id = payload.get("event_id") or payload.get("id") or f"evt_{hash(body) & 0xffff}"
    event_type = payload.get("event") or payload.get("type") or "payment.captured"
    if event_id in _seen:
        publish("webhook.duplicate_ignored", {"event_id": event_id})
        return {"status":"duplicate_ignored", "event_id": event_id}
    _seen.add(event_id)
    publish("webhook.received", {"event_id": event_id, "type": event_type})

    # extract payment info - support both real Razorpay shape and our simulation {payment_id, razorpay_payment_id}
    payment_id = payload.get("payment_id") or (payload.get("payload",{}).get("payment",{}).get("entity",{}).get("id"))
    razorpay_pid = payload.get("razorpay_payment_id") or payment_id
    # find payment by id or create update
    pay = None
    if payment_id:
        pay = db.query(Payment).filter(Payment.id==payment_id).first()
    if not pay and razorpay_pid:
        pay = db.query(Payment).filter(Payment.razorpay_payment_id==razorpay_pid).first()
    if not pay:
        # fallback: latest pending payment
        pay = db.query(Payment).filter(Payment.status=="pending").order_by(Payment.created_at.desc()).first()
    if not pay:
        return {"status":"no pending payment found", "event_id": event_id}

    if "failed" in event_type:
        pay.status="failed"
        if pay.order_id:
            ord=db.query(Order).filter(Order.id==pay.order_id).first()
            if ord: ord.status="failed"
        db.commit()
        ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_failed", amount=pay.amount, policy_result="n/a", authorization="n/a", result="failed", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id})
        db.add(ae); db.commit()
        publish("payment.failed", {"payment_id": pay.id})
        return {"status":"failed processed", "payment_id": pay.id}

    # captured
    pay.status="captured"
    if razorpay_pid: pay.razorpay_payment_id=razorpay_pid
    if pay.order_id:
        ord=db.query(Order).filter(Order.id==pay.order_id).first()
        if ord:
            ord.status="paid"
            chk=db.query(Checkout).filter(Checkout.id==ord.checkout_id).first()
            if chk: chk.status="captured"
    db.commit()
    ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_captured", amount=pay.amount, policy_result="n/a", authorization="n/a", result="captured", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id})
    db.add(ae); db.commit()
    publish("payment.captured", {"payment_id": pay.id})
    return {"status":"captured", "payment_id": pay.id, "event_id": event_id}
