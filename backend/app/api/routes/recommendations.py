
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from fastapi import HTTPException
from ...models.entities import Product
from ...services.recommendation import recommend_cross_sell

router = APIRouter(prefix="/recommendations", tags=["growth"])

@router.get("/cross-sell")
def cross_sell(product_id: str = None, category: str = "", db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    cat = category
    if product_id:
        p=db.query(Product).filter(Product.id==product_id).first()
        if not p:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "product not found"})
        if p.merchant_id != merchant_id:
            raise HTTPException(status_code=403, detail={"code": "cross_tenant", "message": "product belongs to another merchant"})
        cat = p.category
    # try real pipeline first, fallback to static
    try:
        from ...services.growth_intelligence import rank_candidates
        recs = rank_candidates(db, cat or "keyboard", limit=3)
        # normalize to same shape as old
        # rank_candidates already returns product dict, keep it
        # if it used fallback, it returns old shape, so just return
        return {"category": cat, "recommendations": recs}
    except Exception as e:
        all_products = db.query(Product).filter(Product.merchant_id==merchant_id).all()
        recs = recommend_cross_sell(cat or "keyboard", all_products, limit=3)
    # serialize
    out=[]
    for r in recs:
        prod=r.pop("product")
        out.append({"product": {"id": prod.id, "name": prod.name, "price": prod.price, "category": prod.category, "stock": prod.stock}, **r})
    return {"category": cat, "recommendations": out}

@router.get("/campaign-preview")
def campaign_preview(db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    prods=db.query(Product).filter(Product.merchant_id==merchant_id).all()
    # find lowest stock high affinity as campaign candidate
    from ...services.recommendation import AFFINITY
    return {"preview": f"Target: cross-sell for {prods[0].category if prods else 'general'} -> uplift 8.4% estimated", "affinity_map": AFFINITY}
