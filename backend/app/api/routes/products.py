
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product
from ...services.catalog import search_products

router = APIRouter(prefix="/products", tags=["catalog"])

@router.get("")
def list_products(merchant_id: str = None, q: str = "", category: str = "", max_price: int = None, db: Session = Depends(get_db)):
    return search_products(db, merchant_id, q, category, max_price)

@router.get("/search")
def search(q: str = Query("", description="search query"), merchant_id: str = None, category: str = "", max_price: int = None, db: Session = Depends(get_db)):
    return search_products(db, merchant_id, q, category, max_price)

@router.get("/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: return {"error":"not found"}
    return p

@router.get("/{product_id}/inventory")
def inventory(product_id: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: return {"error":"not found"}
    return {"product_id": product_id, "stock": p.stock, "available": p.stock > 0}

@router.post("")
def create_product(payload: dict, db: Session = Depends(get_db)):
    p = Product(**payload)
    db.add(p); db.commit(); db.refresh(p)
    return p
