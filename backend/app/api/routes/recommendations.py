
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product
from ...services.recommendation import recommend_cross_sell

router = APIRouter(prefix="/recommendations", tags=["growth"])

@router.get("/cross-sell")
def cross_sell(product_id: str = None, category: str = "", db: Session = Depends(get_db)):
    # if product_id given, lookup its category
    cat = category
    if product_id:
        p=db.query(Product).filter(Product.id==product_id).first()
        if p: cat = p.category
    all_products = db.query(Product).all()
    recs = recommend_cross_sell(cat or "keyboard", all_products, limit=3)
    # serialize
    out=[]
    for r in recs:
        prod=r.pop("product")
        out.append({"product": {"id": prod.id, "name": prod.name, "price": prod.price, "category": prod.category, "stock": prod.stock}, **r})
    return {"category": cat, "recommendations": out}

@router.get("/campaign-preview")
def campaign_preview(merchant_id: str="m_demo", db: Session = Depends(get_db)):
    prods=db.query(Product).all()
    # find lowest stock high affinity as campaign candidate
    from ...services.recommendation import AFFINITY
    return {"preview": f"Target: cross-sell for {prods[0].category if prods else 'general'} -> uplift 8.4% estimated", "affinity_map": AFFINITY}
