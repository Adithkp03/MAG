from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Payment, Order, Checkout, AuditEvent, WebhookEvent
from ...core.events import publish
from ...core.tracing import start_span, end_span
from ...services.razorpay_adapter import verify_webhook_signature, fetch_payment, has_keys
from ...services.outbox import publish_outbox
import json

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _process_event(db: Session, we: WebhookEvent, payload: dict, event_type: str):
    """Stateful processing: received -> processing -> processed/failed.
    Idempotent on provider event_id; safe to retry."""
    we.status = "processing"
    we.attempts = (we.attempts or 0) + 1
    db.commit()
    try:
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {}) if "payload" in payload else {}
        razorpay_order_id = entity.get("order_id") or payload.get("razorpay_order_id")
        razorpay_payment_id = entity.get("id") or payload.get("razorpay_payment_id")

        pay = None
        if razorpay_order_id:
            pay = db.query(Payment).filter(Payment.razorpay_order_id == razorpay_order_id).first()
        if not pay and razorpay_payment_id:
            pay = db.query(Payment).filter(Payment.razorpay_payment_id == razorpay_payment_id).first()
        if not pay:
            we.status = "failed"
            we.last_error = f"payment_not_correlated order={razorpay_order_id}"
            we.processed = False
            db.commit()
            return {"retryable": True, "code": "payment_not_correlated"}

        live_status = None
        if pay.razorpay_payment_id or razorpay_payment_id:
            try:
                pid = pay.razorpay_payment_id or razorpay_payment_id
                if has_keys() and pid and not pid.startswith("order_"):
                    live = await fetch_payment(pid)
                    live_status = (live.get("status") if isinstance(live, dict) else None) or entity.get("status")
                else:
                    live_status = entity.get("status")
            except Exception:
                live_status = entity.get("status")

        is_failed_event = "failed" in event_type
        if is_failed_event and live_status == "captured":
            is_failed_event = False

        if is_failed_event or (live_status == "failed" and "captured" not in event_type):
            pay.status = "failed"
            if pay.razorpay_payment_id is None and razorpay_payment_id:
                pay.razorpay_payment_id = razorpay_payment_id
            if pay.order_id:
                ord = db.query(Order).filter(Order.id == pay.order_id).first()
                if ord:
                    ord.status = "failed"
                chk = db.query(Checkout).filter(Checkout.id == ord.checkout_id).first() if ord else None
                if chk and chk.can_transition("failed"):
                    chk.status = "failed"
            db.commit()
            ae = AuditEvent(merchant_id=pay.merchant_id, action="webhook_payment_failed", amount=pay.amount, policy_result="n/a", authorization="n/a", result="failed", reason=event_type, payload={"event_id": we.event_id, "payment_id": pay.id, "live_status": live_status})
            db.add(ae)
            publish_outbox(db, pay.id, "payment.failed", {"payment_id": pay.id, "event_id": we.event_id})
            we.processed = True
            we.status = "processed"
            db.commit()
            return {"status": "failed processed", "payment_id": pay.id}

        pay.status = "captured"
        if razorpay_payment_id:
            pay.razorpay_payment_id = razorpay_payment_id
        if pay.order_id:
            ord = db.query(Order).filter(Order.id == pay.order_id).first()
            if ord:
                ord.status = "paid"
                chk = db.query(Checkout).filter(Checkout.id == ord.checkout_id).first()
                if chk and chk.can_transition("captured"):
                    chk.status = "captured"
                elif chk and not chk.can_transition("captured") and chk.status != "captured":
                    we.status = "failed"
                    we.last_error = f"invalid_state {chk.status}->captured"
                    db.commit()
                    return {"retryable": False, "code": "invalid_state_transition"}
        db.commit()
        ae = AuditEvent(merchant_id=pay.merchant_id, action="webhook_payment_captured", amount=pay.amount, policy_result="n/a", authorization="n/a", result="captured", reason=event_type, payload={"event_id": we.event_id, "payment_id": pay.id, "razorpay_order_id": razorpay_order_id, "live_status": live_status})
        db.add(ae)
        publish_outbox(db, pay.id, "payment.captured", {"payment_id": pay.id, "event_id": we.event_id, "order_id": pay.order_id})
        we.processed = True
        we.status = "processed"
        db.commit()
        return {"status": "captured", "payment_id": pay.id, "razorpay_order_id": razorpay_order_id}
    except Exception as e:
        we.status = "failed"
        we.last_error = str(e)[:300]
        db.commit()
        raise


@router.post("/razorpay")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    wspan = None
    try:
        body = await request.body()
        sig = request.headers.get("X-Razorpay-Signature", "")
        if not verify_webhook_signature(body, sig):
            raise HTTPException(status_code=401, detail={"code": "signature_verification_failed", "message": "invalid HMAC"})
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            raise HTTPException(status_code=400, detail={"code": "invalid_json", "message": "body not JSON"})
        event_id = payload.get("event_id") or payload.get("id") or payload.get("payload", {}).get("payment", {}).get("entity", {}).get("id")
        if not event_id:
            raise HTTPException(status_code=400, detail={"code": "missing_event_id", "message": "event_id required"})
        event_type = payload.get("event") or payload.get("type") or "payment.captured"

        wspan = start_span("webhook.razorpay", attrs={"event_id": event_id, "event_type": event_type})

        existing = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
        if existing and existing.status == "processed":
            publish("webhook.duplicate_ignored", {"event_id": event_id})
            end_span(wspan, attrs={"result": "duplicate_ignored"})
            return {"status": "duplicate_ignored", "event_id": event_id}
        if existing and existing.status == "processing":
            end_span(wspan, attrs={"result": "already_processing"})
            return {"status": "already_processing", "event_id": event_id}
        if existing and existing.status in ("received", "failed"):
            # retry: reprocess stored event
            we = existing
            we.payload = payload
            result = await _process_event(db, we, payload, event_type)
        else:
            we = WebhookEvent(event_id=event_id, type=event_type, payload=payload, processed=False, status="received", attempts=0)
            db.add(we)
            db.commit()
            result = await _process_event(db, we, payload, event_type)
        if isinstance(result, dict) and result.get("code") == "payment_not_correlated":
            end_span(wspan, status="error", attrs={"result": "payment_not_correlated"})
            raise HTTPException(status_code=202, detail={"code": "payment_not_correlated", "message": "no payment matches razorpay_order_id, retry after reconciliation", "event_id": event_id})
        if isinstance(result, dict) and result.get("code") == "invalid_state_transition":
            end_span(wspan, status="error", attrs={"result": "invalid_state"})
            raise HTTPException(status_code=409, detail={"code": "invalid_state_transition", "message": "cannot transition checkout to captured"})
        if isinstance(result, dict) and result.get("retryable") is False:
            raise HTTPException(status_code=409, detail=result)
        end_span(wspan, attrs={"result": str(result.get('status') if isinstance(result, dict) else result)})
        out = dict(result) if isinstance(result, dict) else {"status": result}
        out.setdefault("event_id", event_id)
        try:
            from ...services.outbox import publish_pending
            publish_pending(db)
        except Exception:
            pass
        return out
    except HTTPException as e:
        if wspan and wspan.get("status") == "running":
            end_span(wspan, status="error", attrs={"code": e.detail.get("code") if isinstance(e.detail, dict) else str(e.detail)})
        raise
    except Exception as e:
        if wspan and wspan.get("status") == "running":
            end_span(wspan, status="error", attrs={"error": str(e)[:200]})
        raise
    finally:
        if wspan and wspan.get("status") == "running":
            end_span(wspan)


@router.get("/events")
def list_webhook_events(limit: int = 20, db: Session = Depends(get_db)):
    return db.query(WebhookEvent).order_by(WebhookEvent.created_at.desc()).limit(limit).all()
