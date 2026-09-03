from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...core.events import publish
from ...models.entities import Campaign, CampaignAudience, CampaignAction, CampaignRun, CampaignMetric, Product
from ...services.growth_intelligence import compute_product_metrics, rank_candidates
from sqlalchemy import text as sql_text

router=APIRouter(prefix="/api/v1/campaigns", tags=["campaigns"])

class ProposeIn(BaseModel):
    merchant_id: str = "m_demo"
    target_category: str
    discount: int = 10
    trigger_product_id: Optional[str] = None
    recommend_product_id: Optional[str] = None
    name: Optional[str] = None

@router.post("/propose")
def propose(body: ProposeIn, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    from ...models.entities import Policy
    pol=db.query(Policy).filter(Policy.merchant_id==body.merchant_id).first()
    max_disc=pol.max_discount if pol else 15
    if body.discount > max_disc:
        raise HTTPException(status_code=403, detail={"code":"policy_blocked","message":f"discount {body.discount}% exceeds max {max_disc}%","details":{"max_discount":max_disc}})
    data=compute_product_metrics(db, body.merchant_id)
    base_metric=next((m for m in data["metrics"] if (m["category"] or "").lower()==body.target_category.lower()), None)
    cands=rank_candidates(db, body.target_category, body.merchant_id, limit=1)
    rec=cands[0] if cands else None
    trigger=body.trigger_product_id or (rec["product"]["id"] if rec else None)
    base_orders=base_metric["orders_with_category"] if base_metric else 0
    lift_orders=max(1, int(base_orders*0.3)) if base_orders else 1
    price=rec["product"]["price"] if rec else 79900
    incremental=int(lift_orders * price * (1 - body.discount/100))
    aff = rec["affinity"] if rec else 0
    stk = rec["product"]["stock"] if rec else "?"
    reason=f"Target {body.target_category} buyers: attach {aff:.0%} vs baseline, {base_orders} base orders, stock {stk}. Expected +{lift_orders} orders."
    camp=Campaign(
        merchant_id=body.merchant_id,
        name=body.name or f"Cross-sell {body.target_category}->{rec['product']['category'] if rec else '?' } {body.discount}% off",
        target_category=body.target_category,
        discount=body.discount,
        trigger_product_id=trigger,
        recommend_product_id=rec["product"]["id"] if rec else body.recommend_product_id,
        proposal_reason=reason,
        expected_incremental_paise=incremental,
        status="proposed"
    )
    db.add(camp); db.flush()
    try: publish("campaign.created", {"campaign_id": camp.id, "target": body.target_category, "discount": body.discount})
    except: pass
    db.add(CampaignAudience(campaign_id=camp.id, segment=f"{body.target_category}_buyers", customer_count=base_orders))
    db.add(CampaignAction(campaign_id=camp.id, action_type="discount_cross_sell", payload={"target": body.target_category, "discount": body.discount, "recommend": rec["product"]["id"] if rec else None}))
    db.commit(); db.refresh(camp)
    return {"campaign_id": camp.id, "status": camp.status, "name": camp.name, "reason": camp.proposal_reason, "expected_incremental_inr": round(incremental/100,2), "requires_approval": True, "policy": {"max_discount": max_disc, "result": "proposed"}}

@router.post("/{campaign_id}/approve")
def approve(campaign_id: str, approved_by: str = Header(None, alias="X-Approved-By"), db: Session = Depends(get_db)):
    camp=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not camp: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if camp.status!="proposed": raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"campaign already {camp.status}"})
    if not approved_by: raise HTTPException(status_code=422, detail={"code":"validation_error","message":"X-Approved-By header required"})
    camp.status="approved"
    camp.approved_by=approved_by; camp.approved_at=datetime.utcnow()
    try: publish("campaign.approved", {"campaign_id": camp.id, "approved_by": approved_by})
    except: pass
    db.commit()
    return {"campaign_id": camp.id, "status": camp.status, "approved_by": approved_by}

@router.post("/{campaign_id}/execute")
def execute(campaign_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    camp=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not camp: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if camp.status!="approved": raise HTTPException(status_code=409, detail={"code":"invalid_state","message":"campaign must be approved before execute"})
    run=CampaignRun(campaign_id=camp.id, status="running")
    db.add(run); db.flush()
    camp.status="active"
    try: publish("campaign.executed", {"campaign_id": camp.id, "run_id": run.id})
    except: pass
    db.commit()
    met=CampaignMetric(campaign_id=camp.id, run_id=run.id, impressions=0, conversions=0, revenue_paise=0, uplift_paise=0)
    db.add(met); db.commit()
    run.status="completed"; run.ended_at=datetime.utcnow(); db.commit()
    return {"campaign_id": camp.id, "run_id": run.id, "status": camp.status, "message":"campaign activated"}

@router.get("")
def list_campaigns(merchant_id: str="m_demo", db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    rows=db.query(Campaign).filter(Campaign.merchant_id==merchant_id).order_by(Campaign.created_at.desc()).all()
    return {"campaigns": [{"id": c.id, "name": c.name, "target": c.target_category, "discount": c.discount, "status": c.status, "expected_inr": round(c.expected_incremental_paise/100,2), "reason": c.proposal_reason} for c in rows]}

@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    c=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not c: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    aud=db.query(CampaignAudience).filter(CampaignAudience.campaign_id==c.id).all()
    acts=db.query(CampaignAction).filter(CampaignAction.campaign_id==c.id).all()
    runs=db.query(CampaignRun).filter(CampaignRun.campaign_id==c.id).all()
    mets=db.query(CampaignMetric).filter(CampaignMetric.campaign_id==c.id).all()
    total_rev=sum(m.revenue_paise for m in mets)
    total_conv=sum(m.conversions for m in mets)
    uplift_pct=round((total_rev - c.expected_incremental_paise)/max(c.expected_incremental_paise,1)*100,1) if total_rev else None
    return {"campaign": {"id": c.id, "name": c.name, "status": c.status, "reason": c.proposal_reason, "expected_inr": round(c.expected_incremental_paise/100,2), "measured_inr": round(total_rev/100,2), "measured_conversions": total_conv, "uplift_vs_expected_pct": uplift_pct, "approved_by": c.approved_by}, "audience": [{"segment": a.segment, "count": a.customer_count} for a in aud], "actions": [{"type": a.action_type, "payload": a.payload} for a in acts], "runs": [{"id": r.id, "status": r.status} for r in runs], "metrics": [{"conversions": m.conversions, "revenue_inr": round(m.revenue_paise/100,2), "uplift_paise": m.uplift_paise} for m in mets]}

@router.post("/{campaign_id}/metric")
def record_metric(campaign_id: str, conversions: int=0, revenue_paise: int=0, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    c=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not c: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    met=CampaignMetric(campaign_id=c.id, conversions=conversions, revenue_paise=revenue_paise, uplift_paise=revenue_paise)
    db.add(met); db.commit()
    return {"campaign_id": c.id, "conversions": conversions, "revenue_inr": round(revenue_paise/100,2)}
