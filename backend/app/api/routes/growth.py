
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...services.growth_intelligence import compute_product_metrics, compute_customer_metrics, rank_candidates, get_order_history, compute_co_purchase

router = APIRouter(prefix="/growth", tags=["growth"])

@router.get("/metrics/products")
def product_metrics(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    return compute_product_metrics(db, merchant_id)

@router.get("/metrics/customers")
def customer_metrics(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    return compute_customer_metrics(db, merchant_id)

@router.get("/co-purchase")
def co_purchase(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    rows=get_order_history(db, merchant_id, 1000)
    return compute_co_purchase(rows)

@router.get("/rank")
def rank(category: str, merchant_id: str = Depends(require_merchant_auth), limit: int=3, db: Session = Depends(get_db)):
    return {"category": category, "candidates": rank_candidates(db, category, merchant_id, limit)}

@router.get("/opportunities")
def opportunities(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    """P2 real opportunity detection: Orders -> Profiles -> Affinity gaps -> Expected revenue"""
    data=compute_product_metrics(db, merchant_id)
    co=data.get("co_purchase", {})
    metrics=data.get("metrics", [])
    order_count=co.get("order_count",0)
    # Build opportunities by scanning each category as context
    opps=[]
    for m in metrics:
        ctx=(m["category"] or "").lower()
        if not ctx: continue
        cands=rank_candidates(db, ctx, merchant_id, limit=2)
        for cand in cands:
            # cand has product, score, affinity, conversion_rate
            aff=cand.get("affinity",0)
            prod=cand.get("product",{})
            # expected incremental: base_orders * aff * price * discount factor (10%)
            base_orders=m.get("orders_with_category",0)
            price=prod.get("price",0)
            expected_orders=int(base_orders*aff*0.5) if base_orders else 1
            expected_orders=max(1, expected_orders)
            expected_rev=int(expected_orders * price * 0.9)  # 10% discount
            # only surface if convincing evidence
            if aff>0.3 and base_orders>=2:
                opps.append({
                    "context_category": ctx,
                    "context_product": m["name"],
                    "base_orders": base_orders,
                    "recommend": prod.get("name"),
                    "recommend_category": prod.get("category"),
                    "recommend_price": price,
                    "affinity": round(aff,3),
                    "score": cand.get("score"),
                    "expected_orders": expected_orders,
                    "expected_revenue_inr": round(expected_rev/100,2),
                    "evidence": f"{aff:.0%} attach from {order_count} orders, {base_orders} base",
                    "opportunity": f"{ctx} buyers attach {prod.get('category')} at {aff:.0%} — high inventory {prod.get('stock')}, propose cross-sell"
                })
    # sort by expected revenue
    opps.sort(key=lambda x: x["expected_revenue_inr"], reverse=True)
    # fallback if no strong evidence: show at least top 2
    if not opps and metrics:
        for m in metrics[:2]:
            opps.append({"context_category": m["category"], "context_product": m["name"], "opportunity": f"Explore cross-sell for {m['category']} — {m['stock']} in stock, attach {m['attach_rate']:.0%}", "affinity": m["attach_rate"], "expected_revenue_inr": 0, "evidence": "insufficient history for high-confidence estimate"})
    return {"opportunities": opps[:5], "order_count": order_count, "pipeline": "Orders -> Feature Engineering -> Profiles -> Candidate Generation -> Ranking -> Policy Constraints -> Expected Revenue -> Recommendation -> Outcome Tracking"}

@router.get("/intelligence")
def intelligence(merchant_id: str = Depends(require_merchant_auth), db: Session = Depends(get_db)):
    """Full intelligence snapshot for growth agent"""
    prod=compute_product_metrics(db, merchant_id)
    cust=compute_customer_metrics(db, merchant_id)
    co=prod.get("co_purchase",{})
    return {"merchant_id": merchant_id, "order_count": co.get("order_count",0), "product_metrics": prod.get("metrics",[])[:6], "customer_segments": cust[:3], "co_purchase": co, "note": "Learning loop: shown -> clicked -> added_to_cart -> purchased -> revenue measured after campaign"}
