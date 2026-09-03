
# Phase 5 - Growth Engine: deterministic scoring + explainability
AFFINITY = {
    "laptop": ["mouse","bag","keyboard","mousepad","headset"],
    "keyboard": ["mouse","mousepad","headset"],
    "mouse": ["mousepad","keyboard"],
    "phone": ["case","charger","headset"],
    "camera": ["sd card","tripod","bag"],
    "headset": ["mousepad","keyboard"],
}

def recommend_cross_sell(product_category: str, catalog_products: list, cart_total: int = 0, limit=3):
    """Score = affinity + inventory_score + margin_score + conversion_placeholder"""
    cat = (product_category or "").lower().strip()
    targets = AFFINITY.get(cat, [])
    # fallback: if category not in map, use most stocked items as cross-sell
    scored=[]
    for p in catalog_products:
        pcat = (p.category or "").lower()
        score = 0.0
        reason_parts=[]
        if pcat in targets:
            score += 0.6
            reason_parts.append(f"customers buying {product_category} frequently buy {pcat}")
        # inventory bonus
        if p.stock > 50:
            score += 0.15
            reason_parts.append("high availability")
        elif p.stock > 0:
            score += 0.05
        # margin bonus: mid-price items score higher
        if 50000 < p.price < 300000:
            score += 0.1
            reason_parts.append("high conversion price band")
        # avoid recommending same category as cart
        if pcat == cat:
            score -= 0.3
        if score > 0:
            reason = "; ".join(reason_parts) if reason_parts else "general affinity"
            # expected uplift mock
            uplift = round(score * 8.5, 1)
            scored.append((score, p, reason, uplift))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"product": p, "score": round(s,2), "reason": r, "expected_uplift_pct": u, "policy_note": "discount <=15% if applied"} for s,p,r,u in scored[:limit]]

def score_recommendation(product, customer_history: dict = None):
    s=0.5
    if product.stock>0: s+=0.2
    if product.category in AFFINITY: s+=0.1
    return s
