
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...services.growth_intelligence import compute_product_metrics, compute_customer_metrics, rank_candidates, get_order_history, compute_co_purchase

router = APIRouter(prefix="/growth", tags=["growth"])

@router.get("/metrics/products")
def product_metrics(merchant_id: str="m_demo", db: Session = Depends(get_db)):
    return compute_product_metrics(db, merchant_id)

@router.get("/metrics/customers")
def customer_metrics(merchant_id: str="m_demo", db: Session = Depends(get_db)):
    return compute_customer_metrics(db, merchant_id)

@router.get("/co-purchase")
def co_purchase(merchant_id: str="m_demo", db: Session = Depends(get_db)):
    rows=get_order_history(db, merchant_id, 1000)
    return compute_co_purchase(rows)

@router.get("/rank")
def rank(category: str, merchant_id: str="m_demo", limit: int=3, db: Session = Depends(get_db)):
    return {"category": category, "candidates": rank_candidates(db, category, merchant_id, limit)}

@router.get("/opportunities")
def opportunities(merchant_id: str="m_demo", db: Session = Depends(get_db)):
    data=compute_product_metrics(db, merchant_id)
    # find biggest gap: low attach but high inventory
    opps=[]
    for m in data["metrics"]:
        if m["attach_rate"] < 0.2 and m["stock"]>30 and m["conversion_rate"]>0:
            opps.append({"category": m["category"], "product": m["name"], "attach_rate": m["attach_rate"], "conversion": m["conversion_rate"], "stock": m["stock"], "opportunity": f"{m['category']} buyers under-index on attach ({m['attach_rate']:.0%} vs avg)"})
    return {"opportunities": opps[:5], "order_count": data["co_purchase"]["order_count"] if "co_purchase" in data else 0}
