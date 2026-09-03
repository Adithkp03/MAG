
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...models.entities import Product
from ...schemas import ProductCreate, ProductOut, ErrorResponse
from ...services.catalog import search_products

router = APIRouter(prefix="/products", tags=["catalog"])

@router.get("")
def list_products(merchant_id: str = None, q: str = "", category: str = "", max_price: int = None, db: Session = Depends(get_db)):
    rows=search_products(db, merchant_id, q, category, max_price)
    # manual serialize to avoid Pydantic ORM mismatch
    return [{"id":r.id,"name":r.name,"description":r.description,"price":r.price,"category":r.category,"stock":r.stock,"merchant_id":r.merchant_id} for r in rows]

@router.get("/search")
def search(q: str = Query("", description="search query"), merchant_id: str = None, category: str = "", max_price: int = None, db: Session = Depends(get_db)):
    rows=search_products(db, merchant_id, q, category, max_price)
    return [{"id":r.id,"name":r.name,"description":r.description,"price":r.price,"category":r.category,"stock":r.stock,"merchant_id":r.merchant_id} for r in rows]

@router.get("/{product_id}", response_model=ProductOut, responses={404: {"model": ErrorResponse}})
def get_product(product_id: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: raise HTTPException(status_code=404, detail={"code":"not_found","message":"product not found"})
    return p

@router.get("/{product_id}/inventory")
def inventory(product_id: str, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: raise HTTPException(status_code=404, detail={"code":"not_found","message":"product not found"})
    return {"product_id": product_id, "stock": p.stock, "available": p.stock > 0}

@router.post("", response_model=ProductOut, responses={400: {"model": ErrorResponse}})
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    p = Product(**payload.model_dump())
    db.add(p); db.commit(); db.refresh(p)
    return p
