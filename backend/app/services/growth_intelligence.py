
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta

def get_order_history(db: Session, merchant_id: str, limit: int = 1000):
    # Join orders -> checkouts -> carts -> cart_items -> products to build co-purchase
    q = text("""
        SELECT o.id as order_id, o.status, o.total, o.created_at,
               c.id as cart_id, ci.product_id, p.name, p.category, p.price, p.stock
        FROM orders o
        JOIN checkouts ch ON o.checkout_id = ch.id
        JOIN carts c ON ch.cart_id = c.id
        JOIN cart_items ci ON ci.cart_id = c.id
        JOIN products p ON p.id = ci.product_id
        WHERE o.merchant_id = :mid AND o.status IN ('paid','pending')
        ORDER BY o.created_at DESC LIMIT :lim
    """)
    rows = db.execute(q, {"mid": merchant_id, "lim": limit}).mappings().all()
    return rows

def compute_co_purchase(rows):
    # rows: list of order item rows, group by order_id
    from collections import defaultdict, Counter
    order_items = defaultdict(list)
    for r in rows:
        order_items[r["order_id"]].append(r["category"] or r["name"])
    pair_counts = Counter()
    single_counts = Counter()
    for items in order_items.values():
        for cat in items:
            single_counts[cat.lower()] += 1
        # pairs
        for i in range(len(items)):
            for j in range(i+1, len(items)):
                a,b = sorted([items[i].lower(), items[j].lower()])
                pair_counts[f"{a}|{b}"] += 1
    # affinity = P(b|a) = pair / single[a] - stored as string keys a->b
    affinity = {}
    for k, cnt in pair_counts.items():
        a,b = k.split("|")
        affinity[f"{a}->{b}"] = cnt / single_counts[a] if single_counts[a] else 0
        affinity[f"{b}->{a}"] = cnt / single_counts[b] if single_counts[b] else 0
    return {"pair_counts": dict(pair_counts), "single_counts": dict(single_counts), "affinity": affinity, "order_count": len(order_items)}

def compute_product_metrics(db: Session, merchant_id: str):
    rows = get_order_history(db, merchant_id, 1000)
    stats = compute_co_purchase(rows)
    # also inventory/margin from products table
    prods = db.execute(text("SELECT id, name, category, price, stock FROM products WHERE merchant_id=:mid"), {"mid": merchant_id}).mappings().all()
    metrics=[]
    for p in prods:
        cat = (p["category"] or "").lower()
        conv = stats["single_counts"].get(cat, 0) / max(stats["order_count"],1)  # how often category appears
        attach = sum(v for k,v in stats["affinity"].items() if k.startswith(f"{cat}->")) / max(len([k for k in stats["affinity"] if k.startswith(f"{cat}->")]),1)
        metrics.append({
            "product_id": p["id"], "name": p["name"], "category": p["category"],
            "price": p["price"], "stock": p["stock"],
            "orders_with_category": stats["single_counts"].get(cat,0),
            "conversion_rate": round(conv,3),
            "attach_rate": round(attach,3),
            "order_count": stats["order_count"]
        })
    return {"metrics": metrics, "co_purchase": stats}

def compute_customer_metrics(db: Session, merchant_id: str="m_demo"):
    rows = db.execute(text("""
        SELECT customer_id, COUNT(*) as freq, AVG(total) as aov, MAX(created_at) as last_order
        FROM orders WHERE merchant_id=:mid GROUP BY customer_id
    """), {"mid": merchant_id}).mappings().all()
    out=[]
    for r in rows:
        cid=r["customer_id"]
        freq=r["freq"]; aov=r["aov"] or 0
        last=r["last_order"]
        recency = (datetime.utcnow() - last).days if last else 999
        # category affinity per customer
        cats = db.execute(text("""
            SELECT p.category, COUNT(*) as cnt FROM orders o
            JOIN checkouts ch ON o.checkout_id=ch.id JOIN carts c ON ch.cart_id=c.id JOIN cart_items ci ON ci.cart_id=c.id JOIN products p ON p.id=ci.product_id
            WHERE o.customer_id=:cid GROUP BY p.category ORDER BY cnt DESC LIMIT 3
        """), {"cid": cid}).mappings().all()
        out.append({"customer_id": cid, "frequency": freq, "aov": round(float(aov)/100,2), "recency_days": recency, "top_categories": [c["category"] for c in cats]})
    return out

def rank_candidates(db: Session, context_category: str, merchant_id: str="m_demo", limit: int=3):
    # Candidate generation: all products not in context, filter by policy, rank by attach_rate*conversion*inventory
    data = compute_product_metrics(db, merchant_id)
    metrics_by_cat = {m["category"].lower(): m for m in data["metrics"] if m["category"]}
    co = data["co_purchase"]
    candidates=[]
    for m in data["metrics"]:
        cat=(m["category"] or "").lower()
        if cat == (context_category or "").lower():
            continue
        # affinity P(cat | context)
        aff = co["affinity"].get(f"{(context_category or '').lower()}->{cat}", 0)
        # score = 0.5*aff + 0.2*conversion + 0.2*attach + 0.1*inventory
        inv_score = 0.15 if m["stock"]>50 else 0.05 if m["stock"]>0 else 0
        score = 0.5*aff + 0.2*m["conversion_rate"] + 0.2*m["attach_rate"] + inv_score
        # if no order history, fallback to static affinity
        if co["order_count"] < 3:
            # fallback: use previous static scoring
            from .recommendation import recommend_cross_sell
            # let fallback handle
            continue
        candidates.append((score, m, aff))
    if not candidates or co["order_count"] < 3:
        # fallback to old recommendation
        from .recommendation import recommend_cross_sell
        from ..models.entities import Product
        all_prods = db.query(Product).all()
        return recommend_cross_sell(context_category, all_prods, limit=limit)
    candidates.sort(key=lambda x: x[0], reverse=True)
    out=[]
    for score,m,aff in candidates[:limit]:
        out.append({"product": {"id": m["product_id"], "name": m["name"], "category": m["category"], "price": m["price"], "stock": m["stock"]},
                    "score": round(score,3), "reason": f"attach {aff:.0%} from {m['order_count']} orders, conv {m['conversion_rate']:.0%}, stock {m['stock']}",
                    "recommendation_score": round(score,3), "affinity": round(aff,3), "conversion_rate": m["conversion_rate"], "expected_uplift_pct": None, "note": "uplift measured only after campaign outcome"})
    return out
