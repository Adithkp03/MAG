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
    merchant_id: str = Depends(require_merchant_auth)
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
def approve(campaign_id: str, approved_by: str = Header(None, alias="X-Approved-By"), db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    from ...models.entities import Approval
    camp=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not camp: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if camp.merchant_id != merchant:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"campaign belongs to another merchant"})
    # HITL resumable: PROPOSED/AWAITING -> APPROVED, idempotent if already approved
    if camp.status=="approved": return {"campaign_id": camp.id, "status": camp.status, "approved_by": camp.approved_by, "note": "already approved (idempotent)"}
    if camp.status not in ("proposed","awaiting_approval"):
        raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"campaign status {camp.status} not approvable (expected proposed/awaiting_approval)"})
    if not approved_by or not approved_by.strip(): raise HTTPException(status_code=422, detail={"code":"validation_error","message":"X-Approved-By header required"})
    approver=approved_by.strip()
    # bind approval to exact action: merchant + campaign + budget + policy version + action hash
    appr=db.query(Approval).filter(Approval.campaign_id==camp.id, Approval.status=="pending").order_by(Approval.created_at.desc()).first()
    if appr:
        if appr.merchant_id != merchant:
            raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"approval belongs to another merchant"})
        if appr.policy_version != camp.policy_version:
            appr.status="expired"
            db.commit()
            raise HTTPException(status_code=409, detail={"code":"stale_policy","message":"policy version changed since escalation — re-plan required"})
        from ...services.autonomous_growth import _action_hash
        if camp.action_hash and _action_hash(camp.id, camp.discount or 0, camp.budget_paise or 0, camp.policy_version) != camp.action_hash:
            appr.status="expired"
            db.commit()
            raise HTTPException(status_code=409, detail={"code":"action_mutated","message":"action changed after escalation — re-plan required"})
        if appr.expires_at and appr.expires_at < datetime.utcnow():
            appr.status="expired"
            db.commit()
            raise HTTPException(status_code=409, detail={"code":"approval_expired","message":"approval expired — re-plan required"})
        appr.approved_by=approver; appr.status="approved"; appr.decided_at=datetime.utcnow()
        camp.approved_amount=appr.amount
    else:
        # direct approval (auto path or legacy): create binding record
        appr=Approval(merchant_id=merchant, campaign_id=camp.id, action="execute_campaign", amount=camp.budget_paise or 0, status="approved", requested_by="campaign-api", approved_by=approver, policy_version=camp.policy_version, decided_at=datetime.utcnow())
        db.add(appr)
        camp.approved_amount=camp.budget_paise or 0
    camp.status="approved"
    camp.approved_by=approver; camp.approved_at=datetime.utcnow()
    try: publish("campaign.approved", {"campaign_id": camp.id, "approved_by": approver})
    except: pass
    db.commit()
    return {"campaign_id": camp.id, "status": camp.status, "approved_by": approver, "approval_id": appr.id, "bound_amount": appr.amount, "policy_version": appr.policy_version}

@router.post("/{campaign_id}/reject")
def reject(campaign_id: str, reason: str="rejected", approved_by: str = Header(None, alias="X-Approved-By"), db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    camp=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not camp: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if camp.merchant_id != merchant:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"campaign belongs to another merchant"})
    if camp.status not in ("proposed","awaiting_approval"):
        raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"campaign status {camp.status} not rejectable"})
    camp.status="rejected"
    camp.approved_by=approved_by; camp.approved_at=datetime.utcnow()
    db.commit()
    return {"campaign_id": camp.id, "status": camp.status}

@router.post("/{campaign_id}/execute")
def execute(campaign_id: str, simulation_mode: bool = True, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    from ...services.autonomous_growth import execute_campaign as _exec
    camp=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not camp: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if camp.merchant_id != merchant:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"campaign belongs to another merchant"})
    # Phase 13: PROPOSED->awaiting_approval->APPROVED->EXECUTING->COMPLETED
    if camp.status=="proposed":
        # auto-transition to awaiting_approval for HITL visibility
        camp.status="awaiting_approval"; db.commit()
        raise HTTPException(status_code=409, detail={"code":"awaiting_approval","message":"campaign requires approval before execute (PROPOSED->AWAITING_APPROVAL). Call /approve with X-Approved-By."})
    if camp.status=="awaiting_approval":
        raise HTTPException(status_code=409, detail={"code":"awaiting_approval","message":"campaign awaiting approval"})
    if camp.status not in ("approved","executing"):
        raise HTTPException(status_code=409, detail={"code":"invalid_state","message":f"campaign status {camp.status} not executable (expected approved)"})
    res=_exec(db, campaign_id, simulation_mode=simulation_mode)
    if not res: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if "error" in res: raise HTTPException(status_code=409, detail={"code":"execute_rejected","message":res["error"]})
    met=res["metric"]
    sim=bool(res.get("simulation_mode", True))
    label="Demo simulation — not observed customer behavior" if sim else "Observed"
    return {"campaign_id": camp.id, "run_id": None, "status": res["campaign"].status, "message": f"campaign executed ({label})", "simulation_mode": sim, "treatment": res.get("treatment"), "control": res.get("control"), "incremental_revenue_inr": round((met.incremental_revenue or 0)/100,2), "incremental_margin_inr": round((met.incremental_margin or 0)/100,2), "sample_adequate": met.sample_adequate}

@router.get("")
def list_campaigns(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    rows=db.query(Campaign).filter(Campaign.merchant_id==merchant_id).order_by(Campaign.created_at.desc()).all()
    return {"campaigns": [{"id": c.id, "name": c.name, "target": c.target_category, "discount": c.discount, "status": c.status, "expected_inr": round(c.expected_incremental_paise/100,2), "reason": c.proposal_reason} for c in rows]}

@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), merchant=Depends(require_merchant_auth)):
    c=db.query(Campaign).filter(Campaign.id==campaign_id).first()
    if not c: raise HTTPException(status_code=404, detail={"code":"not_found","message":"campaign not found"})
    if c.merchant_id != merchant:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"campaign belongs to another merchant"})
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
    if c.merchant_id != merchant:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"campaign belongs to another merchant"})
    met=CampaignMetric(campaign_id=c.id, conversions=conversions, revenue_paise=revenue_paise, uplift_paise=revenue_paise)
    db.add(met); db.commit()
    return {"campaign_id": c.id, "conversions": conversions, "revenue_inr": round(revenue_paise/100,2)}
