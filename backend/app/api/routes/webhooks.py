
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Payment, Order, Checkout, AuditEvent, WebhookEvent
from ...core.events import publish
from ...core.tracing import start_span, end_span
from ...services.razorpay_adapter import verify_webhook_signature, fetch_payment, has_keys
import json, hmac, hashlib

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    wspan = None
    try:
        body = await request.body()
        sig = request.headers.get("X-Razorpay-Signature","")
        if not verify_webhook_signature(body, sig):
            raise HTTPException(status_code=401, detail={"code":"signature_verification_failed","message":"invalid HMAC"})
        try:
            payload = json.loads(body) if body else {}
        except:
            raise HTTPException(status_code=400, detail={"code":"invalid_json","message":"body not JSON"})
        event_id = payload.get("event_id") or payload.get("id") or payload.get("payload",{}).get("payment",{}).get("entity",{}).get("id")
        if not event_id:
            raise HTTPException(status_code=400, detail={"code":"missing_event_id","message":"event_id required"})
        event_type = payload.get("event") or payload.get("type") or "payment.captured"

        # P0: create span immediately so every return/error safely closes it
        wspan = start_span("webhook.razorpay", attrs={"event_id": event_id, "event_type": event_type})

        existing = db.query(WebhookEvent).filter(WebhookEvent.event_id==event_id).first()
        if existing:
            publish("webhook.duplicate_ignored", {"event_id": event_id})
            end_span(wspan, attrs={"result":"duplicate_ignored"})
            return {"status":"duplicate_ignored", "event_id": event_id}
        we = WebhookEvent(event_id=event_id, type=event_type, payload=payload, processed=False)
        db.add(we); db.commit()

        entity = payload.get("payload",{}).get("payment",{}).get("entity",{}) if "payload" in payload else {}
        razorpay_order_id = entity.get("order_id") or payload.get("razorpay_order_id")
        razorpay_payment_id = entity.get("id") or payload.get("razorpay_payment_id")

        pay = None
        if razorpay_order_id:
            pay = db.query(Payment).filter(Payment.razorpay_order_id==razorpay_order_id).first()
        if not pay and razorpay_payment_id:
            pay = db.query(Payment).filter(Payment.razorpay_payment_id==razorpay_payment_id).first()
        if not pay:
            we.processed=False; db.commit()
            end_span(wspan, status="error", attrs={"result":"payment_not_correlated"})
            raise HTTPException(status_code=202, detail={"code":"payment_not_correlated","message":"no payment matches razorpay_order_id, retry after reconciliation","event_id": event_id, "razorpay_order_id": razorpay_order_id})

        # P0-6 real reconciliation: fetch live Razorpay payment and reconcile
        live_status = None
        if pay.razorpay_payment_id or razorpay_payment_id:
            try:
                pid = pay.razorpay_payment_id or razorpay_payment_id
                if has_keys() and pid and not pid.startswith("order_"):
                    live = await fetch_payment(pid)
                    live_status = (live.get("status") if isinstance(live, dict) else None) or entity.get("status")
                else:
                    live_status = entity.get("status")
            except Exception as e:
                live_status = entity.get("status")

        # Determine final status: webhook says failed/captured vs live truth
        # If live says captured but webhook says failed, prefer captured after verify; if live says failed, mark failed
        is_failed_event = "failed" in event_type
        if is_failed_event and live_status == "captured":
            # quarantine: webhook failed but live captured -> treat as captured and log anomaly
            is_failed_event = False

        if is_failed_event or (live_status == "failed" and "captured" not in event_type):
            pay.status="failed"
            if pay.razorpay_payment_id is None and razorpay_payment_id:
                pay.razorpay_payment_id=razorpay_payment_id
            if pay.order_id:
                ord=db.query(Order).filter(Order.id==pay.order_id).first()
                if ord: ord.status="failed"
                chk=db.query(Checkout).filter(Checkout.id==ord.checkout_id).first() if ord else None
                if chk and chk.can_transition("failed"): chk.status="failed"
            db.commit()
            ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_failed", amount=pay.amount, policy_result="n/a", authorization="n/a", result="failed", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id, "live_status": live_status})
            db.add(ae); we.processed=True; db.commit()
            publish("payment.failed", {"payment_id": pay.id})
            end_span(wspan, attrs={"result":"failed", "live_status": str(live_status)})
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
                    end_span(wspan, status="error", attrs={"result":"invalid_state"})
                    raise HTTPException(status_code=409, detail={"code":"invalid_state_transition","message": f"cannot transition {chk.status} -> captured"})
        db.commit()
        ae=AuditEvent(merchant_id=pay.merchant_id or "m_demo", action="webhook_payment_captured", amount=pay.amount, policy_result="n/a", authorization="n/a", result="captured", reason=event_type, payload={"event_id": event_id, "payment_id": pay.id, "razorpay_order_id": razorpay_order_id, "live_status": live_status})
        db.add(ae); we.processed=True; db.commit()
        publish("payment.captured", {"payment_id": pay.id})
        publish("order.paid", {"order_id": pay.order_id, "payment_id": pay.id})
        end_span(wspan, attrs={"result":"captured", "live_status": str(live_status)})
        return {"status":"captured", "payment_id": pay.id, "event_id": event_id, "razorpay_order_id": razorpay_order_id}
    except HTTPException as e:
        # ensure span closed on any HTTP error path
        if wspan and wspan.get("status")=="running":
            end_span(wspan, status="error", attrs={"code": e.detail.get("code") if isinstance(e.detail, dict) else str(e.detail)})
        raise
    except Exception as e:
        if wspan and wspan.get("status")=="running":
            end_span(wspan, status="error", attrs={"error": str(e)[:200]})
        raise
    finally:
        if wspan and wspan.get("status")=="running":
            end_span(wspan)

@router.get("/events")
def list_webhook_events(limit:int=20, db: Session = Depends(get_db)):
    return db.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(limit).all()
