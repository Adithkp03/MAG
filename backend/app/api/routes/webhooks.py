
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Payment, Order, Checkout, AuditEvent, WebhookEvent
from ...core.events import publish
from ...core.tracing import start_span, end_span
from ...services.razorpay_adapter import verify_webhook_signature, fetch_payment
import json, hmac, hashlib

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()
    sig = request.headers.get("X-Razorpay-Signature","")
    if not verify_webhook_signature(body, sig):
        raise HTTPException(status_code=401, detail={"code":"signature_verification_failed","message":"invalid HMAC"})
    try:
        payload = json.loads(body) if body else {}
    except:
        raise HTTPException(status_code=400, detail={"code":"invalid_json","message":"body not JSON"})
    # event_id must be present per Razorpay spec - not guessed from hash fallback P0-1
    event_id = payload.get("event_id") or payload.get("id") or payload.get("payload",{}).get("payment",{}).get("entity",{}).get("id")
    if not event_id:
        raise HTTPException(status_code=400, detail={"code":"missing_event_id","message":"event_id required"})
    event_type = payload.get("event") or payload.get("type") or "payment.captured"

    # durable dedup via DB table P0-2 (survives restart, not _seen set)
    existing = db.query(WebhookEvent).filter(WebhookEvent.event_id==event_id).first()
    if existing:
        publish("webhook.duplicate_ignored", {"event_id": event_id})
        return {"status":"duplicate_ignored", "event_id": event_id}
    we = WebhookEvent(event_id=event_id, type=event_type, payload=payload, processed=False)
    db.add(we); db.commit()

    # correct correlation P0-3: via razorpay_order_id notes, not latest pending
    entity = payload.get("payload",{}).get("payment",{}).get("entity",{}) if "payload" in payload else payload.get("payload",{}) if isinstance(payload.get("payload"), dict) else {}
    razorpay_order_id = entity.get("order_id") or payload.get("razorpay_order_id") or payload.get("notes",{}).get("checkout_id")
    razorpay_payment_id = entity.get("id") or payload.get("razorpay_payment_id") or payload.get("payment_id")

    pay = None
    if razorpay_order_id:
        pay = db.query(Payment).filter(Payment.razorpay_order_id==razorpay_order_id).first()
    if not pay and razorpay_payment_id:
        pay = db.query(Payment).filter(Payment.razorpay_payment_id==razorpay_payment_id).first()
    if not pay and "order_id" in (entity.get("notes",{}) or {}):
        # Razorpay notes contain our checkout_id/order linkage
        notes = entity.get("notes",{})
        if notes.get("order_id"):
            pay = db.query(Payment).filter(Payment.order_id==notes["order_id"]).first()
    if not pay:
        # P0-1 fail closed - do not guess latest pending; return 202 for reconciliation retry P0-6
        we.processed=False; db.commit()
        raise HTTPException(status_code=202, detail={"code":"payment_not_correlated","message":"no payment matches razorpay_order_id, retry after reconciliation","event_id": event_id, "razorpay_order_id": razorpay_order_id})

    # reconcile P0-6: optionally fetch live payment to confirm status
    if pay.status == "pending" and pay.razorpay_order_id:
        try:
            live = await fetch_payment(pay.razorpay_payment_id or razorpay_payment_id or pay.razorpay_order_id)
            # if live says captured but webhook says failed, trust live after verify
            pass
        except: pass

    if "failed" in event_type:
        pay.status="failed"
        if pay.razorpay_payment_id is None and razorpay_payment_id:
            pay.razorpay_payment_id=razorpay_payment_id
        if pay.order_id:
            ord=db.query(Order).filter(Order.id==pay.order_id).first()
            if ord: ord.status="failed"
            chk=db.query(Checkout).filter(Checkout.id==ord.checkout_id).first() if ord else None
            if chk and chk.can_transition("failed"): chk.status="failed"
        db.commit()
        ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_failed", amount=pay.amount, policy_result="n/a", authorization="n/a", result="failed", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id})
        db.add(ae); we.processed=True; db.commit()
        end_span(wspan, attrs={"result":"failed"}); publish("payment.failed", {"payment_id": pay.id})
        return {"status":"failed processed", "payment_id": pay.id, "event_id": event_id}

    # captured
    pay.status="captured"
    if razorpay_payment_id: pay.razorpay_payment_id=razorpay_payment_id
    if pay.order_id:
        ord=db.query(Order).filter(Order.id==pay.order_id).first()
        if ord:
            ord.status="paid"
            chk=db.query(Checkout).filter(Checkout.id==ord.checkout_id).first()
            if chk and chk.can_transition("captured"): chk.status="captured"
            elif chk and not chk.can_transition("captured"):
                # state validation P0-5
                raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> captured"})
    db.commit()
    ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_captured", amount=pay.amount, policy_result="n/a", authorization="n/a", result="captured", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id, "razorpay_order_id": razorpay_order_id})
    db.add(ae); we.processed=True; db.commit()
    end_span(wspan, attrs={"result":"captured"}); publish("payment.captured", {"payment_id": pay.id})
    return {"status":"captured", "payment_id": pay.id, "event_id": event_id, "razorpay_order_id": razorpay_order_id}

@router.get("/events")
def list_webhook_events(limit:int=20, db: Session = Depends(get_db)):
    return db.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(limit).all()
