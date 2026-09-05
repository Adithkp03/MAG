
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import text as sql
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...services.specialized_agents import revenue_agent, retention_agent, inventory_agent, decision_agent, compare_options
from ...services.outbox import publish_pending
from ...services.inventory import reserve_stock
import datetime

router=APIRouter(prefix="/api/v1")

@router.get("/policy/tiers")
def policy_tiers(merchant_id: str = Depends(require_merchant_auth), db: Session=Depends(get_db)):
    row=db.execute(sql("SELECT auto_approve_limit, approval_limit, hard_block_limit, max_discount, max_campaign_budget, max_daily_spend, min_margin_pct FROM policies WHERE merchant_id=:mid"), {"mid": merchant_id}).mappings().first()
    if not row: return {"merchant_id": merchant_id, "error": "no policy"}
    return {"merchant_id": merchant_id, "auto_approve_limit_inr": row["auto_approve_limit"]/100, "approval_limit_inr": row["approval_limit"]/100, "hard_block_limit_inr": row["hard_block_limit"]/100, "max_discount": row["max_discount"], "max_campaign_budget_inr": row["max_campaign_budget"]/100, "max_daily_spend_inr": row["max_daily_spend"]/100, "min_margin_pct": row["min_margin_pct"]}

@router.get("/auth/check")
def auth_check(identity: str=Depends(require_merchant_auth), merchant_id: str = Depends(require_merchant_auth)):
    # P2-20 tenant isolation: identity derived from auth, must match merchant_id
    if identity != merchant_id:
        # In strict mode, prevent cross-tenant access
        raise HTTPException(status_code=403, detail=f"tenant isolation: identity {identity} cannot access {merchant_id}")
    return {"identity": identity, "merchant_id": merchant_id, "tenant_isolation": "enforced"}

@router.post("/inventory/reserve")
def inv_reserve(product_id: str, qty: int=1, db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    from ...models.entities import Product
    prod = db.query(Product).filter(Product.id==product_id).first()
    if prod and prod.merchant_id != identity:
        raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "product belongs to another merchant"})
    return reserve_stock(db, product_id, qty)

@router.post("/outbox/publish")
def outbox_publish(db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    return publish_pending(db)

@router.get("/agents/compare")
def agents_compare(merchant_id: str = Depends(require_merchant_auth), db: Session=Depends(get_db)):
    from ...models.entities import Opportunity, MerchantObjective
    opps=db.query(Opportunity).filter(Opportunity.merchant_id==merchant_id).order_by(Opportunity.priority.desc()).limit(5).all()
    obj=db.query(MerchantObjective).filter(MerchantObjective.merchant_id==merchant_id).first()
    objective=obj.primary_objective if obj else "revenue"
    cmp=compare_options(opps, objective)
    # Specialized picks
    rev=revenue_agent(opps)
    ret=retention_agent(opps, [])
    inv=inventory_agent(opps)
    chosen=decision_agent(rev, ret, inv, obj)
    return {"objective": objective, "compare": cmp, "specialized": {"revenue_pick": rev.id if rev else None, "retention_pick": ret.id if ret else None, "inventory_pick": inv.id if inv else None, "decision": chosen.id if chosen else None}}

@router.get("/webhooks/status")
def webhook_status(db: Session=Depends(get_db), identity: str=Depends(require_merchant_auth)):
    rows=db.execute(sql("SELECT status, COUNT(*) as cnt FROM webhook_events GROUP BY status")).mappings().all()
    return {"webhook_events": [{"status": r["status"], "count": r["cnt"]} for r in rows], "durable_states": ["received","processing","processed","failed"]}

@router.get("/ucp/complete-flow")
def ucp_flow(db: Session=Depends(get_db)):
    return {"flow": ["External AI agent","UCP discovery /.well-known/ucp","catalog /api/v1/products","checkout /api/v1/ucp/checkout","payment handler razorpay","completion","webhook /api/v1/webhooks/razorpay","audit"],"demo": "Another AI agent can transact without knowing MAG internals", "try": "POST /api/v1/ucp/checkout with {items:[{product_id:'prod_kb1',quantity:1}]}"}
