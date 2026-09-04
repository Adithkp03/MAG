
from fastapi import APIRouter, Depends, Request, Header, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...core.tracing import start_span, end_span
from ...services.autonomous_growth import (
    compute_customer_intelligence, compute_product_intelligence,
    detect_opportunities, score_opportunities, plan_action,
    record_outcome, learning_update, run_autonomous_cycle, ensure_merchant_objective
)
import uuid, json
router=APIRouter(prefix="/api/v1")

class ObjectiveIn(BaseModel):
    primary_objective: str="revenue"  # revenue/margin/clearance/retention
    risk_tolerance: str="medium"
    min_margin_pct: int=10
    max_campaign_budget: int=1000000  # paise
    max_discount: int=15

@router.get("/merchant/objectives")
def get_objectives(merchant_id: str="m_demo", db: Session=Depends(get_db)):
    from ...models.entities import MerchantObjective
    obj=db.query(MerchantObjective).filter(MerchantObjective.merchant_id==merchant_id).first()
    if not obj:
        obj=ensure_merchant_objective(db, merchant_id)
    return {"merchant_id": merchant_id, "primary_objective": obj.primary_objective, "risk_tolerance": obj.risk_tolerance, "min_margin_pct": obj.min_margin_pct, "max_campaign_budget": obj.max_campaign_budget, "max_discount": obj.max_discount}

@router.put("/merchant/objectives")
def set_objectives(body: ObjectiveIn, merchant_id: str="m_demo", db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    from ...models.entities import MerchantObjective
    obj=db.query(MerchantObjective).filter(MerchantObjective.merchant_id==merchant_id).first()
    if not obj:
        obj=MerchantObjective(merchant_id=merchant_id)
        db.add(obj)
    obj.primary_objective=body.primary_objective
    obj.risk_tolerance=body.risk_tolerance
    obj.min_margin_pct=body.min_margin_pct
    obj.max_campaign_budget=body.max_campaign_budget
    obj.max_discount=body.max_discount
    db.commit(); db.refresh(obj)
    return {"ok": True, "merchant_id": merchant_id, "objectives": body.dict()}

@router.get("/customers/intelligence")
@router.get("/intelligence/customers")
def customers(db: Session=Depends(get_db), merchant_id: str="m_demo"):
    from ...core.cache import cache_get, cache_set
    cache_key = f"intel:customers:{merchant_id}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit
    data=compute_customer_intelligence(db, merchant_id)
    res = {"merchant_id": merchant_id, "count": len(data), "customers": data, "cached": False}
    cache_set(cache_key, res, ttl=60)
    return res

@router.get("/products-intel")
@router.get("/intelligence/products")
def products_intel(db: Session=Depends(get_db), merchant_id: str="m_demo"):
    from ...core.cache import cache_get, cache_set
    cache_key = f"intel:products:{merchant_id}"
    hit = cache_get(cache_key)
    if hit is not None:
        return hit
    data=compute_product_intelligence(db, merchant_id)
    res = {"merchant_id": merchant_id, "count": len(data), "products": data, "cached": False}
    cache_set(cache_key, res, ttl=60)
    return res

@router.get("/opportunities")
def opps(db: Session=Depends(get_db), merchant_id: str="m_demo"):
    from ...models.entities import Opportunity
    try:
        all=db.query(Opportunity).filter(Opportunity.merchant_id==merchant_id).order_by(Opportunity.priority.desc()).all()
    except Exception as e:
        return {"merchant_id": merchant_id, "count": 0, "opportunities": [], "warning": f"db unavailable: {str(e)[:120]}"}
    return {"merchant_id": merchant_id, "count": len(all),
            "opportunities": [{"opportunity_id": o.id, "type": o.type, "evidence": o.evidence, "target_segment": o.target_segment, "recommended_product_id": o.recommended_product_id, "recommended_action": o.recommended_action, "expected_revenue_inr": round((o.expected_revenue or 0)/100,2), "expected_margin_inr": round((o.expected_margin or 0)/100,2), "confidence": o.confidence, "risk": o.risk, "priority": o.priority, "status": o.status, "created_at": str(o.created_at)} for o in all]}

@router.post("/opportunities/detect")
def detect(merchant_id: str="m_demo", db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    try:
        opps=detect_opportunities(db, merchant_id)
        scored=score_opportunities(db, merchant_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"db temporarily unavailable: {str(e)[:120]}")
    return {"merchant_id": merchant_id, "detected": len(opps), "top": {"id": scored[0].id, "type": scored[0].type, "priority": scored[0].priority} if scored else None}

@router.post("/opportunities/{opp_id}/plan")
def plan(opp_id: str, db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    res=plan_action(db, opp_id)
    if not res: raise HTTPException(status_code=404, detail="opportunity not found")
    opp=res["opportunity"]; camp=res["campaign"]
    return {"opportunity_id": opp.id, "type": opp.type, "campaign_id": camp.id, "campaign_status": camp.status, "audience_count": res["audience_count"], "offer": res["offer"], "budget_inr": res["budget_inr"], "economics": res["economics"], "policy": res["policy"], "next": res["next"]}

# Autonomous Run MAG
@router.post("/autonomous/run")
def run_cycle(merchant_id: str="m_demo", db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth), request: Request=None):
    sp=start_span("autonomous.run", {"merchant_id": merchant_id})
    res=run_autonomous_cycle(db, merchant_id)
    end_span(sp, 0)
    return res

@router.post("/campaigns/{camp_id}/outcome")
def outcome(camp_id: str, funnel: dict, db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    met=record_outcome(db, camp_id, funnel)
    if not met: raise HTTPException(status_code=404, detail="campaign not found")
    return {"campaign_id": camp_id, "metric_id": met.id, "impressions": met.impressions, "conversions": met.conversions, "revenue_inr": round((met.revenue_paise or 0)/100,2), "uplift_inr": round((met.uplift_paise or 0)/100,2), "incremental_conversions": getattr(met,'incremental_conversions',0), "control_conversions": getattr(met,'control_conversions',0), "uplift_pct": getattr(met,'uplift_pct',0)}

@router.post("/campaigns/{camp_id}/execute")
def execute(camp_id: str, db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    from ...services.autonomous_growth import execute_campaign
    res=execute_campaign(db, camp_id)
    if not res: raise HTTPException(status_code=404, detail="campaign not found")
    if "error" in res: raise HTTPException(status_code=400, detail=res["error"])
    camp=res["campaign"]; funnel=res["funnel"]; met=res["metric"]
    return {"campaign_id": camp.id, "status": camp.status, "funnel": funnel, "revenue_inr": round((met.revenue_paise or 0)/100,2), "incremental_revenue_inr": round((met.uplift_paise or 0)/100,2), "uplift_pct": getattr(met,'uplift_pct',0)}

@router.post("/learning/update")
def learn(merchant_id: str="m_demo", db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    ups=learning_update(db, merchant_id)
    return {"merchant_id": merchant_id, "updated": len(ups), "updates": ups}

@router.get("/explain/{opp_id}")
def explain(opp_id: str, db: Session=Depends(get_db)):
    from ...models.entities import Opportunity
    opp=db.query(Opportunity).filter(Opportunity.id==opp_id).first()
    if not opp: raise HTTPException(status_code=404, detail="not found")
    ev=opp.evidence or {}
    # Evidence panel
    return {"opportunity_id": opp.id, "type": opp.type,
            "WHY": f"{ev.get('affinity', ev.get('churned_count',''))} signal: {opp.recommended_action}",
            "EVIDENCE": ev,
            "CURRENT": {"target": opp.target_segment, "priority": opp.priority},
            "IMPACT": {"expected_revenue_inr": round((opp.expected_revenue or 0)/100,2), "expected_margin_inr": round((opp.expected_margin or 0)/100,2)},
            "RISK": opp.risk, "CONFIDENCE": opp.confidence,
            "formula": "Score = ExpectedIncrementalMargin * Prob * Strategic - Cost - Risk"}
