
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...services.evaluation import full_evaluation, offline_replay

router=APIRouter(prefix="/evaluation", tags=["evaluation"])

@router.get("")
def evaluation(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    return full_evaluation(db, merchant_id)

@router.get("/replay")
def replay(merchant_id: str = Depends(require_merchant_auth), n: int=1000, db: Session = Depends(get_db)):
    return offline_replay(db, merchant_id, n)

@router.get("/kpis")
def kpis(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    ev=full_evaluation(db, merchant_id)
    return {"commerce": ev["commerce"], "growth": ev["growth"], "agent_quality": ev["agent_quality"], "reliability": ev["reliability"]}
