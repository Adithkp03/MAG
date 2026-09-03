
"""
Event workers consuming Redis Streams (or memory fallback).
AuditWorker -> AuditEvent already written inline, but also tallies
AnalyticsWorker -> aggregates order metrics
NotificationWorker -> logs notifications
ReconciliationWorker -> verifies payment vs order state
"""
from sqlalchemy.orm import Session
from ..core.database import SessionLocal
from ..core.events import list_stream
from sqlalchemy import text as sql_text
import time

def audit_worker(limit=10):
    # in this MVP, audit is already written synchronously; worker verifies AuditEvent count vs streams
    db=SessionLocal()
    try:
        from ..models.entities import AuditEvent
        cnt=db.query(AuditEvent).count()
        streams=len(list_stream("all", 100))
        return {"audit_events": cnt, "stream_events": streams, "lag": streams-cnt}
    finally: db.close()

def analytics_worker():
    db=SessionLocal()
    try:
        row=db.execute(sql_text("SELECT COUNT(*) as cnt, COALESCE(SUM(total),0) as rev FROM orders WHERE status='paid'")).mappings().first()
        return {"paid_orders": row["cnt"], "paid_revenue_paise": int(row["rev"])}
    finally: db.close()

def reconciliation_worker():
    db=SessionLocal()
    try:
        # find payments pending but webhook not yet captured
        rows=db.execute(sql_text("""
            SELECT p.id, p.razorpay_order_id, p.status, o.status as o_status, ch.status as ch_status
            FROM payments p LEFT JOIN orders o ON p.order_id=o.id LEFT JOIN checkouts ch ON o.checkout_id=ch.id
            WHERE p.status='pending'
        """)).mappings().all()
        return {"pending_payments": len(rows), "samples": [dict(r) for r in rows][:3]}
    finally: db.close()

def notification_worker():
    # placeholder: would send email/slack for campaign/payout
    events=list_stream("campaign.approved", 5)
    return {"campaign_approved_events": len(events), "last": events[-1] if events else None}

def run_all():
    return {
        "audit": audit_worker(),
        "analytics": analytics_worker(),
        "reconciliation": reconciliation_worker(),
        "notification": notification_worker()
    }
