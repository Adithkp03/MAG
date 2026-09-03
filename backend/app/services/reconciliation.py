
"""Reconciliation: scheduled worker for stale pending payments + webhook quarantine"""
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta
from ..models.entities import Payment, Order, Checkout, AuditEvent
from ..services.razorpay_adapter import fetch_payment, has_keys

async def reconcile_stale_payments(db: Session, stale_minutes: int=30) -> dict:
    """Find payments pending older than stale_minutes, fetch live Razorpay status, reconcile DB"""
    cutoff = datetime.utcnow() - timedelta(minutes=stale_minutes)
    stale = db.query(Payment).filter(Payment.status=="pending", Payment.created_at < cutoff).all()
    # also include all pending if no cutoff (for demo)
    if not stale:
        stale = db.query(Payment).filter(Payment.status=="pending").limit(20).all()
    results=[]
    for pay in stale:
        # try fetch live if we have razorpay_payment_id or order_id
        live_status=None
        try:
            if has_keys() and pay.razorpay_payment_id:
                live=await fetch_payment(pay.razorpay_payment_id)
                live_status=live.get("status") if isinstance(live, dict) else None
            elif has_keys() and pay.razorpay_order_id and pay.razorpay_order_id.startswith("order_"):
                # for order_id we cannot fetch payment directly, try via order fetch if adapter supports
                live_status=None
        except Exception as e:
            live_status=None
        action="skipped"
        if live_status == "captured":
            pay.status="captured"
            if pay.order_id:
                ord=db.query(Order).filter(Order.id==pay.order_id).first()
                if ord: ord.status="paid"
                chk=db.query(Checkout).filter(Checkout.id==ord.checkout_id).first() if ord else None
                if chk and chk.can_transition("captured"): chk.status="captured"
            ae=AuditEvent(merchant_id=pay.merchant_id, action="reconcile_captured", amount=pay.amount, policy_result="n/a", authorization="system", result="captured", reason=f"reconciled live_status captured for {pay.razorpay_order_id}", payload={"payment_id":pay.id, "live_status":live_status})
            db.add(ae); action="reconciled_captured"
        elif live_status in ("failed","cancelled"):
            pay.status="failed"
            if pay.order_id:
                ord=db.query(Order).filter(Order.id==pay.order_id).first()
                if ord: ord.status="failed"
            ae=AuditEvent(merchant_id=pay.merchant_id, action="reconcile_failed", amount=pay.amount, policy_result="n/a", authorization="system", result="failed", reason=f"reconciled live_status {live_status}", payload={"payment_id":pay.id})
            db.add(ae); action="reconciled_failed"
        else:
            # quarantine: no live data, keep pending but flag
            if (datetime.utcnow() - pay.created_at).total_seconds() > 3600*24:
                action="quarantined_stale_24h"
                ae=AuditEvent(merchant_id=pay.merchant_id, action="reconcile_quarantine", amount=pay.amount, policy_result="n/a", authorization="system", result="quarantine", reason="stale >24h no live status", payload={"payment_id":pay.id})
                db.add(ae)
        results.append({"payment_id":pay.id, "razorpay_order_id":pay.razorpay_order_id, "old_status":"pending", "live_status":live_status, "action":action})
    db.commit()
    return {"checked": len(stale), "results": results}
