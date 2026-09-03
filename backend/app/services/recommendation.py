
# Phase 5 - Growth Engine: deterministic scoring + explainability (fallback only when order history <3)
# P2 #11 #12: This is the weakest part - static affinity map. Growth_intelligence is primary when order_count>=3.
AFFINITY = {
    "laptop": ["mouse","bag","keyboard","mousepad","headset"],
    "keyboard": ["mouse","mousepad","headset"],
    "mouse": ["mousepad","keyboard"],
    "phone": ["case","charger","headset"],
    "camera": ["sd card","tripod","bag"],
    "headset": ["mousepad","keyboard"],
}

def recommend_cross_sell(product_category: str, catalog_products: list, cart_total: int = 0, limit=3):
    """Fallback deterministic scoring - used only when evidence insufficient. Score = affinity + inventory + margin."""
    cat = (product_category or "").lower().strip()
    targets = AFFINITY.get(cat, [])
    scored=[]
    for p in catalog_products:
        pcat = (p.category or "").lower()
        score = 0.0
        reason_parts=[]
        if pcat in targets:
            score += 0.6
            reason_parts.append(f"customers buying {product_category} frequently buy {pcat}")
        if p.stock > 50:
            score += 0.15
            reason_parts.append("high availability")
        elif p.stock > 0:
            score += 0.05
        if 50000 < p.price < 300000:
            score += 0.1
            reason_parts.append("high conversion price band")
        if pcat == cat:
            score -= 0.3
        if score > 0:
            reason = "; ".join(reason_parts) if reason_parts else "general affinity"
            scored.append((score, p, reason))
    scored.sort(key=lambda x: x[0], reverse=True)
    # P2 #12: do NOT display fake uplift as measured - show recommendation_score until outcome data exists
    return [{"product": p, "score": round(s,2), "reason": r, "recommendation_score": round(s,2), "expected_uplift_pct": None, "note": "fallback - insufficient order history for measured uplift", "policy_note": "discount <=15% if applied"} for s,p,r in scored[:limit]]

def score_recommendation(product, customer_history: dict = None):
    s=0.5
    if product.stock>0: s+=0.2
    if product.category in AFFINITY: s+=0.1
    return s
