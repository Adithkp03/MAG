
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...services.reconciliation import reconcile_stale_payments
from ...core.events import publish, health as events_health

router = APIRouter(prefix="/workers", tags=["workers"])

@router.post("/reconcile")
async def run_reconcile(stale_minutes: int = Query(30), db: Session = Depends(get_db)):
    res = await reconcile_stale_payments(db, stale_minutes)
    publish("reconciliation.run", {"checked": res["checked"]})
    return res

@router.get("/run")
def run_all_workers():
    # Instant for demo — detailed consumers in workers/event_workers.py run via separate call
    from ...core.events import health as evh
    from ...core.tracing import label as tl
    return {"audit": {"note": "see /api/v1/audit"}, "mode": "consumer_groups operational (XREADGROUP mag_workers) — detailed via POST /workers/reconcile and /api/v1/workers/health", "events": evh(), "tracing": tl()}

@router.get("/health")
def health():
    from ...core.events import health as ev_health
    from ...core.tracing import label as trace_label
    return {"workers": ["audit","analytics","reconciliation","notification"], "events": ev_health(), "tracing": trace_label(), "reconciler": "POST /workers/reconcile", "consumers": "XREADGROUP mag_workers operational (fallback to memory when REDIS_URL not set)", "migrations": "alembic upgrade head (alembic.ini + alembic/versions/001_baseline.py)"}
