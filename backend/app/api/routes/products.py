from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ...core.database import get_db
from ...core.auth import require_merchant_auth
from ...models.entities import Product
from ...schemas import ProductCreate, ProductOut, ErrorResponse
from ...services.catalog import search_products

router = APIRouter(prefix="/products", tags=["catalog"])

@router.get("")
def list_products(q: str = "", category: str = "", max_price: int = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    # pagination + input sanitization: clamp max_price, strip q
    q = (q or "").strip()[:100]
    category = (category or "").strip()[:50]
    if max_price is not None and (max_price < 0 or max_price > 100000000):
        raise HTTPException(status_code=422, detail={"code":"invalid_price","message":"max_price out of range"})
    rows=search_products(db, merchant_id, q, category, max_price)
    total = len(rows)
    paged = rows[offset:offset+limit]
    # manual serialize to avoid Pydantic ORM mismatch — include cost_price & margin
    def ser(r):
        cp=getattr(r,'cost_price',None)
        margin=round((r.price-cp)/r.price*100) if cp and r.price else None
        return {"id":r.id,"name":r.name,"description":r.description,"price":r.price,"cost_price":cp,"margin_pct":margin,"category":r.category,"stock":r.stock,"merchant_id":r.merchant_id}
    items = [ser(r) for r in paged]
    # add pagination headers via response? return envelope
    return {"products": items, "total": total, "limit": limit, "offset": offset, "has_more": offset+limit < total}

@router.get("/search")
def search(q: str = Query("", description="search query"), category: str = "", max_price: int = None, limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0), db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    q = (q or "").strip()[:100]
    rows=search_products(db, merchant_id, q, category, max_price)
    total = len(rows)
    paged = rows[offset:offset+limit]
    def ser(r):
        cp=getattr(r,'cost_price',None)
        margin=round((r.price-cp)/r.price*100) if cp and r.price else None
        return {"id":r.id,"name":r.name,"description":r.description,"price":r.price,"cost_price":cp,"margin_pct":margin,"category":r.category,"stock":r.stock,"merchant_id":r.merchant_id}
    return {"products": [ser(r) for r in paged], "total": total, "limit": limit, "offset": offset}

@router.get("/{product_id}", response_model=ProductOut, responses={404: {"model": ErrorResponse}})
def get_product(product_id: str, db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: raise HTTPException(status_code=404, detail={"code":"not_found","message":"product not found"})
    if p.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"product belongs to another merchant"})
    # inject derived margin for response
    cp=getattr(p,'cost_price',None)
    try:
        p.margin_pct=round((p.price-cp)/p.price*100) if cp and p.price else None
    except: pass
    return p

@router.get("/{product_id}/inventory")
def inventory(product_id: str, db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    p = db.query(Product).filter(Product.id==product_id).first()
    if not p: raise HTTPException(status_code=404, detail={"code":"not_found","message":"product not found"})
    if p.merchant_id != merchant_id:
        raise HTTPException(status_code=403, detail={"code":"cross_tenant","message":"product belongs to another merchant"})
    return {"product_id": product_id, "stock": p.stock, "available": p.stock > 0, "reserved": getattr(p, 'reserved', 0)}

@router.post("", response_model=ProductOut, responses={400: {"model": ErrorResponse}})
def create_product(payload: ProductCreate, db: Session = Depends(get_db), merchant_id: str = Depends(require_merchant_auth)):
    # payload already validated via Pydantic; extra sanitize price/stock
    if payload.price < 0 or payload.price > 100000000:
        raise HTTPException(status_code=422, detail={"code":"invalid_price","message":"price out of range"})
    if payload.cost_price is not None and (payload.cost_price < 0 or payload.cost_price > payload.price):
        raise HTTPException(status_code=422, detail={"code":"invalid_cost","message":"cost_price must be 0 <= cost <= price"})
    data=payload.model_dump()
    data["merchant_id"] = merchant_id  # authenticated identity wins over body
    # derive cost_price if not provided: 75% of price (25% margin) — Phase 3 no defaults in intelligence, but allow API default for convenience
    if data.get("cost_price") is None:
        data["cost_price"]=int(data["price"]*0.75)
    p = Product(**data)
    # ensure instance has margin for response
    try: p.margin_pct=round((p.price-p.cost_price)/p.price*100) if p.cost_price else None
    except: pass
    db.add(p); db.commit(); db.refresh(p)
    try: p.margin_pct=round((p.price-p.cost_price)/p.price*100) if p.cost_price else None
    except: pass
    return p
