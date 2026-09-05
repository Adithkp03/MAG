
from sqlalchemy.orm import Session
from ..models.entities import OutboxEvent
import datetime
def publish_outbox(db: Session, aggregate_id: str, event_type: str, payload: dict):
    """P2-23 transactional outbox: write in same transaction, background publisher moves to Redis"""
    evt=OutboxEvent(aggregate_id=aggregate_id, event_type=event_type, payload=payload, status="pending")
    db.add(evt); db.flush()
    return evt

def publish_pending(db: Session):
    """Background publisher: move pending to published and push to Redis Streams"""
    from ..core.events import publish as redis_publish
    pending=db.query(OutboxEvent).filter(OutboxEvent.status=="pending").limit(20).all()
    published=0
    for e in pending:
        try:
            payload=dict(e.payload or {})
            payload["_outbox_id"]=e.id  # consumer-side dedup key
            redis_publish(e.event_type, payload)
            e.status="published"; e.published_at=datetime.datetime.utcnow()
            published+=1
        except Exception:
            e.status="failed"
    db.commit()
    return {"published": published, "total": len(pending)}
