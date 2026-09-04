
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...agent.growth_runtime import run_growth_agent
router=APIRouter(prefix="/api/v1/growth-agent", tags=["growth-agent"])
class GrowthRunIn(BaseModel):
    merchant_id: str = Depends(require_merchant_auth)
    message: str = "Find the best growth opportunity for this merchant and estimate campaign impact"
@router.post("/run")
def growth_run(body: GrowthRunIn, db: Session = Depends(get_db)):
    res=run_growth_agent(db, merchant_id=body.merchant_id, user_message=body.message)
    run=res["run"]
    return {"run_id": run.id, "status": run.status, "final_reply": run.final_reply, "tool_calls": res["tool_calls"], "fallback": res.get("fallback", False)}
@router.get("/runs/{run_id}")
def growth_run_get(run_id: str, db: Session = Depends(get_db)):
    from ...models.entities import AgentRun
    r=db.query(AgentRun).filter(AgentRun.id==run_id).first()
    if not r: return {"error":"not found"}
    return {"id": r.id, "status": r.status, "final_reply": r.final_reply, "user_message": r.user_message}
