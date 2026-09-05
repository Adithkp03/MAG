
"""Autonomous Growth Engine — P0 #1-12
- 10 opportunity types
- Real customer/product intelligence
- Scoring: Expected Incremental Margin * Prob * Strategic - Cost - Risk
- Merchant objectives
- Action planner + Audience engine + Outcome funnel + Learning loop + Incrementality
"""
from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text, func
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import uuid, json, statistics

def ensure_merchant_objective(db: Session, merchant_id: str):
    from ..models.entities import MerchantObjective
    obj=db.query(MerchantObjective).filter(MerchantObjective.merchant_id==merchant_id).first()
    if not obj:
        obj=MerchantObjective(merchant_id=merchant_id, primary_objective="revenue", risk_tolerance="medium", min_margin_pct=10, max_campaign_budget=1000000, max_discount=15)
        db.add(obj); db.commit(); db.refresh(obj)
    return obj

def _learned_or_cohort(db: Session, merchant_id: str, learn_key: str,
                       opp_type: str, category: str | None = None) -> dict:
    """LearningState posterior wins if it has real observations; else
    historical cohort estimate; else cold-start prior (explicitly labeled).
    The prior mean comes from conversion.COLD_START_PRIORS — the single
    labeled table of hardcoded rates — and is always reported as
    source='prior', never as observed behavior."""
    from .conversion import cohort_conversion, cold_start_prior
    try:
        from ..models.entities import LearningState
        ls = db.query(LearningState).filter(
            LearningState.merchant_id == merchant_id,
            LearningState.key == learn_key).first()
        if ls and (ls.observations or 0) >= 10:
            import math
            se = math.sqrt(max(0.0, (ls.mean or 0) * (1 - (ls.mean or 0)) / max(1, ls.observations)))
            return {
                "predicted_conversion": round(ls.mean, 4),
                "sample_size": ls.observations,
                "confidence": round(max(0.0, min(1.0, 1.0 - 3.92 * se)), 3),
                "source": "learned",
                "is_cold_start": False,
            }
    except Exception:
        pass
    try:
        est = cohort_conversion(db, merchant_id, opp_type, category)
        if est["source"] != "prior":
            return est
    except Exception:
        pass
    return {
        "predicted_conversion": round(cold_start_prior(opp_type), 4),
        "sample_size": 0,
        "confidence": 0.2,
        "source": "prior",
        "is_cold_start": True,
    }


def _parse_dt(v):
    """SQLite returns DATETIME columns as strings; Postgres as datetime.
    Normalize both so recency math works on either backend."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00").split("+")[0])
    except Exception:
        return None


def compute_customer_intelligence(db: Session, merchant_id: str="m_demo"):
    """RFM + CLV + churn + segments"""
    from ..models.entities import Customer, CustomerProfile
    # Aggregate orders per customer
    rows=db.execute(sql_text("""
        SELECT o.customer_id, COUNT(*) as freq, COALESCE(SUM(o.total),0) as total, COALESCE(AVG(o.total),0) as aov,
               MAX(o.created_at) as last_at, MIN(o.created_at) as first_at
        FROM orders o WHERE o.merchant_id=:mid AND o.customer_id IS NOT NULL GROUP BY o.customer_id
    """), {"mid": merchant_id}).mappings().all()
    # Global stats for scoring
    all_recencies=[]
    for r in rows:
        _la = _parse_dt(r["last_at"])
        if _la:
            rec=(datetime.utcnow() - _la).days
            all_recencies.append(rec)
    # Build profiles
    out=[]
    for r in rows:
        cid=r["customer_id"]
        freq=int(r["freq"]); total=int(r["total"] or 0); aov=int(r["aov"] or 0)
        last=_parse_dt(r["last_at"]); first=_parse_dt(r["first_at"])
        recency=(datetime.utcnow() - last).days if last else 999
        # tenure
        tenure=(last - first).days if last and first else 0
        # RFM scoring 1-5
        # R: lower recency better
        if recency<=7: r_score=5
        elif recency<=30: r_score=4
        elif recency<=60: r_score=3
        elif recency<=120: r_score=2
        else: r_score=1
        # F
        if freq>=5: f_score=5
        elif freq>=3: f_score=4
        elif freq>=2: f_score=3
        elif freq>=1: f_score=2
        else: f_score=1
        # M: total
        if total>=500000: m_score=5
        elif total>=200000: m_score=4
        elif total>=100000: m_score=3
        elif total>=50000: m_score=2
        else: m_score=1
        rfm=f"{r_score}{f_score}{m_score}"
        # CLV: total * (freq * 0.3 + 1)
        clv=int(total * (1 + freq*0.25))
        # price sensitivity: aov vs median
        price_sens="medium"
        if aov>300000: price_sens="low"
        elif aov<100000: price_sens="high"
        # churn prob: recency/180 capped
        churn=min(0.95, recency/180 * 0.9 + (0.2 if freq==1 else 0))
        # category affinity
        cats=db.execute(sql_text("""
            SELECT p.category, COUNT(*) as cnt FROM orders o
            JOIN checkouts ch ON o.checkout_id=ch.id JOIN carts c ON ch.cart_id=c.id JOIN cart_items ci ON ci.cart_id=c.id JOIN products p ON p.id=ci.product_id
            WHERE o.customer_id=:cid GROUP BY p.category ORDER BY cnt DESC LIMIT 3
        """), {"cid": cid}).mappings().all()
        top_cats=[c["category"] for c in cats]
        pred_next=top_cats[0] if top_cats else None
        # value segment
        if r_score>=4 and f_score>=4: seg="champion"
        elif r_score>=4 and f_score<=2: seg="new"
        elif r_score<=2 and f_score>=3: seg="at_risk"
        elif r_score==1: seg="churned"
        elif total>=300000: seg="high_value"
        else: seg="regular"
        # upsert profile
        prof=db.query(CustomerProfile).filter(CustomerProfile.customer_id==cid).first()
        if not prof:
            prof=CustomerProfile(customer_id=cid, merchant_id=merchant_id)
            db.add(prof)
        prof.r_score=r_score; prof.f_score=f_score; prof.m_score=m_score; prof.rfm_score=rfm
        prof.clv=clv; prof.aov=aov; prof.frequency=freq; prof.recency_days=recency
        prof.category_affinity=top_cats; prof.price_sensitivity=price_sens; prof.churn_prob=round(churn,2)
        prof.predicted_next_category=pred_next; prof.value_segment=seg; prof.last_purchase_at=last
        db.flush()
        out.append({"customer_id": cid, "rfm": rfm, "r": r_score, "f": f_score, "m": m_score, "clv": clv, "clv_inr": round(clv/100,2), "aov_inr": round(aov/100,2), "frequency": freq, "recency_days": recency, "churn_prob": round(churn,2), "segment": seg, "top_categories": top_cats, "predicted_next": pred_next, "price_sensitivity": price_sens})
    # also include customers with no orders (never purchased) — Phase 4 completeness
    try:
        all_cids=set(r["customer_id"] for r in rows)
        no_order=db.execute(sql_text("SELECT id FROM customers WHERE merchant_id=:mid"), {"mid": merchant_id}).mappings().all()
        for row in no_order:
            cid=row["id"]
            if cid in all_cids: continue
            # create profile for zero-order customer
            prof=db.query(CustomerProfile).filter(CustomerProfile.customer_id==cid).first()
            if not prof:
                prof=CustomerProfile(customer_id=cid, merchant_id=merchant_id)
                db.add(prof)
            prof.r_score=1; prof.f_score=1; prof.m_score=1; prof.rfm_score="111"
            prof.clv=0; prof.aov=0; prof.frequency=0; prof.recency_days=999
            prof.category_affinity=[]; prof.price_sensitivity="high"; prof.churn_prob=0.95
            prof.predicted_next_category=None; prof.value_segment="churned"; prof.last_purchase_at=None
            db.flush()
            out.append({"customer_id": cid, "rfm": "111", "r": 1, "f": 1, "m": 1, "clv": 0, "clv_inr": 0, "aov_inr": 0, "frequency": 0, "recency_days": 999, "churn_prob": 0.95, "segment": "churned", "top_categories": [], "predicted_next": None, "price_sensitivity": "high"})
    except Exception as e:
        db.rollback()
    db.commit()
    return out

def compute_product_intelligence(db: Session, merchant_id: str="m_demo"):
    from ..models.entities import Product, ProductProfile
    prods=db.execute(sql_text("SELECT id, name, category, price, cost_price, stock FROM products WHERE merchant_id=:mid"), {"mid": merchant_id}).mappings().all()
    # order stats - computed once
    order_count=db.execute(sql_text("SELECT COUNT(*) as cnt FROM orders WHERE merchant_id=:mid"), {"mid": merchant_id}).mappings().first()["cnt"] or 1
    total_rev=db.execute(sql_text("SELECT COALESCE(SUM(total),0) as rev FROM orders WHERE merchant_id=:mid AND status='paid'"), {"mid": merchant_id}).mappings().first()["rev"] or 1
    # Fix #6: compute co-purchase metrics ONCE and index (was N+1 inside loop)
    from .growth_intelligence import compute_product_metrics
    pm=compute_product_metrics(db, merchant_id)
    pm_index={m["product_id"]: m for m in pm["metrics"]}
    out=[]
    for p in prods:
        pid=p["id"]
        # sales velocity: units sold per day (last 30d)
        sold=db.execute(sql_text("""
            SELECT COALESCE(SUM(ci.quantity),0) as units FROM cart_items ci
            JOIN carts c ON ci.cart_id=c.id JOIN checkouts ch ON c.id=ch.cart_id JOIN orders o ON ch.id=o.checkout_id
            WHERE ci.product_id=:pid AND o.merchant_id=:mid
        """), {"pid": pid, "mid": merchant_id}).mappings().first()["units"] or 0
        velocity=round(sold/30,2) if sold else 0
        # revenue contribution
        prod_rev=db.execute(sql_text("""
            SELECT COALESCE(SUM(ci.line_total),0) as rev FROM cart_items ci
            JOIN carts c ON ci.cart_id=c.id JOIN checkouts ch ON c.id=ch.cart_id JOIN orders o ON ch.id=o.checkout_id
            WHERE ci.product_id=:pid AND o.merchant_id=:mid AND o.status='paid'
        """), {"pid": pid, "mid": merchant_id}).mappings().first()["rev"] or 0
        contrib=round(prod_rev/max(total_rev,1),3)
        # attach rate & conversion from co-purchase (indexed, Fix #6)
        met=pm_index.get(pid)
        attach=met["attach_rate"] if met else 0
        conv=met["conversion_rate"] if met else 0
        # days of inventory
        doi=round(p["stock"]/max(velocity,0.1),1) if velocity else 999
        # Phase 3: real margin from cost_price — no category defaults
        price=p["price"]; cost=p["cost_price"]
        if cost is not None and price and price>0:
            margin=round((price-cost)/price*100)
        elif price and price>0:
            # backfill missing cost_price as 75% of price (25% margin) and persist if possible
            margin=25
            try:
                db.execute(sql_text("UPDATE products SET cost_price=:cp WHERE id=:pid AND cost_price IS NULL"), {"cp": int(price*0.75), "pid": pid})
                db.commit()
            except: db.rollback()
        else:
            margin=0
        # demand trend: velocity vs previous period (simplistic: if sold>2 rising)
        trend="stable"
        if velocity>1.5: trend="rising"
        elif velocity<0.3 and sold>0: trend="falling"
        # slow moving score 0-1
        slow=max(0, min(1, (doi-30)/90)) if doi!=999 else 0.8
        # upsert
        prof=db.query(ProductProfile).filter(ProductProfile.product_id==pid).first()
        if not prof:
            prof=ProductProfile(product_id=pid, merchant_id=merchant_id)
            db.add(prof)
        prof.sales_velocity=velocity; prof.revenue_contribution=contrib; prof.margin_pct=margin; prof.inventory_level=p["stock"]
        prof.days_of_inventory=doi; prof.attach_rate=attach; prof.conversion_rate=conv; prof.demand_trend=trend; prof.slow_moving_score=round(slow,2)
        db.flush()
        # Phase 5: inventory_history snapshot (append daily, keep last 30)
        try:
            from ..models.entities import InventoryHistory
            db.add(InventoryHistory(product_id=pid, merchant_id=merchant_id, stock=p["stock"], velocity=velocity, doi=doi))
            # prune old >30 per product
            hist=db.query(InventoryHistory).filter(InventoryHistory.product_id==pid).order_by(InventoryHistory.recorded_at.desc()).all()
            if len(hist)>30:
                for old in hist[30:]: db.delete(old)
            db.flush()
        except Exception as e:
            db.rollback()
            db.flush()
        out.append({"product_id": pid, "name": p["name"], "category": p["category"], "price": p["price"], "price_inr": round(p["price"]/100,2), "cost_price": cost, "cost_inr": round(cost/100,2) if cost else None, "stock": p["stock"], "velocity": velocity, "revenue_contribution": contrib, "margin_pct": margin, "doi": doi, "attach_rate": attach, "conversion": conv, "trend": trend, "slow_score": round(slow,2)})
    db.commit()
    return out

def detect_opportunities(db: Session, merchant_id: str="m_demo"):
    """10 opportunity types with evidence"""
    from ..models.entities import Opportunity
    # Ensure intelligence fresh
    cust_intel=compute_customer_intelligence(db, merchant_id)
    prod_intel=compute_product_intelligence(db, merchant_id)
    obj=ensure_merchant_objective(db, merchant_id)
    # co-purchase affinity
    from .growth_intelligence import compute_product_metrics, get_order_history, compute_co_purchase
    rows=get_order_history(db, merchant_id, 1000)
    co=compute_co_purchase(rows)
    order_count=co["order_count"]
    # clear previous open to avoid duplicates on each run
    db.query(Opportunity).filter(Opportunity.merchant_id==merchant_id, Opportunity.status=="open").delete()
    db.commit()
    opps=[]

    # Helper to create opp
    def add_opp(typ, evidence, segment, rec_pid, rec_action, exp_rev, exp_margin, conf, risk, priority):
        opp=Opportunity(merchant_id=merchant_id, type=typ, evidence=evidence, target_segment=segment, recommended_product_id=rec_pid, recommended_action=rec_action, expected_revenue=exp_rev, expected_margin=exp_margin, confidence=conf, risk=risk, priority=priority, status="open")
        db.add(opp); db.flush()
        return opp

    # 1. Cross-sell gap
    for m in [x for x in prod_intel if x["attach_rate"]<0.5]:
        # find best attach target
        from .growth_intelligence import rank_candidates
        from .conversion import cohort_conversion
        cands=rank_candidates(db, m["category"], merchant_id, limit=1)
        if cands and cands[0]["affinity"]>0.3:
            cand=cands[0]
            # Data-derived: eligible * conv * price * margin. conv comes from
            # historical cohort + Bayesian smoothing, or LearningState posterior
            # if a previous campaign already measured this pair.
            rec_prod=next((p for p in prod_intel if p["product_id"]==cand["product"]["id"]), None)
            rec_price=rec_prod["price"] if rec_prod else cand["product"]["price"]
            rec_margin=rec_prod["margin_pct"]/100 if rec_prod and rec_prod["margin_pct"] else 0.25
            margin_estimated = not (rec_prod and rec_prod.get("cost_price"))
            eligible=int(order_count*0.3)
            est=_learned_or_cohort(db, merchant_id, f"cross_sell:{m['category']}",
                                   "cross_sell", m["category"])
            conv=est["predicted_conversion"]
            exp_rev=int(eligible * conv * rec_price)
            exp_margin=int(exp_rev * rec_margin * (1 - min(obj.max_discount,8)/100) - 5000)  # minus campaign cost
            exp_margin=max(0, exp_margin)
            add_opp("cross_sell", {"base_category": m["category"], "affinity": cand["affinity"], "order_count": order_count, "attach": m["attach_rate"], "eligible": eligible, "conv": round(conv,3), "conv_source": est["source"], "conv_sample": est["sample_size"], "conv_confidence": est["confidence"], "margin_estimated": margin_estimated, "rec_price": rec_price, "rec_margin": rec_margin}, {"segment": f"{m['category']}_buyers", "count": eligible}, cand["product"]["id"], f"discount {min(obj.max_discount,8)}% cross-sell", exp_rev, exp_margin, round(min(0.95, cand["affinity"]*est["confidence"]+0.3*est["predicted_conversion"]),2) if est["source"]!="prior" else round(cand["affinity"],2), "low", cand["score"])

    # 2. Upsell (high AOV customers, recommend higher priced variant)
    high_val=[c for c in cust_intel if c["aov_inr"]>3000 and c["segment"] in ["high_value","champion"]]
    if high_val:
        lap=next((p for p in prod_intel if p["category"]=="laptop"), None)
        if lap:
            eligible=len(high_val)
            est_u=_learned_or_cohort(db, merchant_id, "upsell:laptop", "upsell", "laptop")
            conv=est_u["predicted_conversion"]; price=lap["price"]; margin=lap["margin_pct"]/100
            margin_estimated = lap.get("cost_price") is None
            exp_rev=int(eligible * conv * price)
            exp_margin=int(exp_rev * margin * 0.95 - 8000)  # 5% discount + 8k cost
            exp_margin=max(0, exp_margin)
            add_opp("upsell", {"high_value_customers": len(high_val), "avg_aov": sum(c["aov_inr"] for c in high_val)/len(high_val), "eligible": eligible, "conv": round(conv,3), "conv_source": est_u["source"], "conv_sample": est_u["sample_size"], "price": price, "margin": margin, "margin_estimated": margin_estimated}, {"customer_ids": [c["customer_id"] for c in high_val][:20], "count": len(high_val)}, lap["product_id"], "bundle upsell 5%", exp_rev, exp_margin, 0.6, "medium", 0.7)

    # 3. Churn-risk
    churned=[c for c in cust_intel if c["churn_prob"]>0.6]
    if churned:
        # winback: avg order value from churned segment, eligible * conv * price * margin - discount - cost
        eligible=len(churned)
        est_c=_learned_or_cohort(db, merchant_id, "churn_risk:global", "churn_risk", None)
        conv=est_c["predicted_conversion"]; price=int(sum(c["aov_inr"] for c in churned)/len(churned)*100) if churned else 200000; margin=0.25
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.90 - 10000)  # 10% discount
        exp_margin=max(0, exp_margin)
        add_opp("churn_risk", {"churned_count": len(churned), "avg_recency": sum(c["recency_days"] for c in churned)/len(churned), "eligible": eligible, "conv": round(conv,3), "conv_source": est_c["source"], "conv_sample": est_c["sample_size"], "price": price}, {"customer_ids": [c["customer_id"] for c in churned][:15], "count": len(churned)}, None, "winback 10% + personalized email", exp_rev, exp_margin, 0.7, "medium", 0.85)

    # 4. Repeat-purchase (customers with freq 1 but recency 30-60)
    repeat=[c for c in cust_intel if c["frequency"]==1 and 30<=c["recency_days"]<=60]
    if repeat:
        eligible=len(repeat)
        est_r=_learned_or_cohort(db, merchant_id, "repeat_purchase:global", "repeat_purchase", None)
        conv=est_r["predicted_conversion"]; price=int(sum(c["aov_inr"] for c in repeat)/len(repeat)*100) if repeat else 200000; margin=0.25
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.92 - 6000)
        exp_margin=max(0, exp_margin)
        add_opp("repeat_purchase", {"repeat_candidates": len(repeat), "eligible": eligible, "conv": round(conv,3), "conv_source": est_r["source"], "conv_sample": est_r["sample_size"]}, {"customer_ids": [c["customer_id"] for c in repeat][:15], "count": len(repeat)}, None, "repeat nudge 8%", exp_rev, exp_margin, 0.65, "low", 0.6)

    # 5. Dead/slow inventory
    dead=[p for p in prod_intel if p["slow_score"]>0.6 and p["stock"]>20]
    for p in dead[:2]:
        eligible=p["stock"]
        est_d=_learned_or_cohort(db, merchant_id, f"dead_stock:{p['category']}", "dead_stock", p["category"])
        conv=est_d["predicted_conversion"]; price=p["price"]; margin=p["margin_pct"]/100
        margin_estimated = p.get("cost_price") is None
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.88 - 7000)  # 12% clearance discount
        exp_margin=max(0, exp_margin)
        add_opp("dead_stock", {"doi": p["doi"], "stock": p["stock"], "velocity": p["velocity"], "eligible": eligible, "conv": round(conv,3), "conv_source": est_d["source"], "conv_sample": est_d["sample_size"], "margin": margin, "margin_estimated": margin_estimated}, {"category": p["category"]}, p["product_id"], "clearance 12% flash", exp_rev, exp_margin, 0.5, "low", 0.55)

    # 6. High-margin promotion
    highm=[p for p in prod_intel if p["margin_pct"]>=30 and p["stock"]>20]
    for p in highm[:2]:
        eligible=int(order_count*0.2)
        est_h=_learned_or_cohort(db, merchant_id, f"high_margin:{p['category']}", "high_margin", p["category"])
        conv=est_h["predicted_conversion"]; price=p["price"]; margin=p["margin_pct"]/100
        margin_estimated = p.get("cost_price") is None
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.95 - 6000)
        exp_margin=max(0, exp_margin)
        add_opp("high_margin", {"margin": p["margin_pct"], "margin_estimated": margin_estimated, "contrib": p["revenue_contribution"], "eligible": eligible, "conv": round(conv,3), "conv_source": est_h["source"], "conv_sample": est_h["sample_size"]}, {"category": p["category"]}, p["product_id"], "feature high-margin 5% push", exp_rev, exp_margin, 0.6, "low", 0.65)

    # 7. Low-margin warning
    lowm=[p for p in prod_intel if p["margin_pct"]<=15]
    for p in lowm[:1]:
        add_opp("low_margin", {"margin": p["margin_pct"]}, {"category": p["category"]}, p["product_id"], "reduce discount, protect margin", 0, 0, 0.8, "high", 0.4)

    # 8. Stock-risk
    risk=[p for p in prod_intel if p["doi"]<7 and p["velocity"]>1]
    for p in risk[:1]:
        add_opp("stock_risk", {"doi": p["doi"], "velocity": p["velocity"]}, {"category": p["category"]}, p["product_id"], "restock urgently, throttle campaign", 0, 0, 0.7, "high", 0.5)

    # 9. High-value customer opportunity (champion)
    champ=[c for c in cust_intel if c["segment"]=="champion"]
    if champ:
        eligible=len(champ)
        est_v=_learned_or_cohort(db, merchant_id, "high_value:global", "high_value", None)
        conv=est_v["predicted_conversion"]; price=int(sum(c["clv_inr"] for c in champ)/len(champ)*100) if champ else 500000; margin=0.30
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.95 - 12000)
        exp_margin=max(0, exp_margin)
        add_opp("high_value", {"champions": len(champ), "avg_clv": sum(c["clv_inr"] for c in champ)/len(champ), "eligible": eligible, "conv": round(conv,3), "conv_source": est_v["source"], "conv_sample": est_v["sample_size"]}, {"customer_ids": [c["customer_id"] for c in champ][:10], "count": len(champ)}, None, "VIP bundle early access", exp_rev, exp_margin, 0.75, "low", 0.9)

    # 10. Abandoned-cart (customers with no orders but have cart - simplified: use churned as proxy)
    # We simulate via churned + high recency
    aband=[c for c in cust_intel if c["recency_days"]>60 and c["frequency"]==1]
    if aband:
        eligible=len(aband)
        est_a=_learned_or_cohort(db, merchant_id, "abandoned_cart:global", "abandoned_cart", None)
        conv=est_a["predicted_conversion"]; price=int(sum(c["aov_inr"] for c in aband)/len(aband)*100) if aband else 200000; margin=0.25
        exp_rev=int(eligible * conv * price)
        exp_margin=int(exp_rev * margin * 0.90 - 7000)
        exp_margin=max(0, exp_margin)
        add_opp("abandoned_cart", {"count": len(aband), "eligible": eligible, "conv": round(conv,3), "conv_source": est_a["source"], "conv_sample": est_a["sample_size"]}, {"customer_ids": [c["customer_id"] for c in aband][:10], "count": len(aband)}, None, "abandoned recovery 10%", exp_rev, exp_margin, 0.6, "low", 0.62)

    db.commit()
    # Score and return
    all_opps=db.query(Opportunity).filter(Opportunity.merchant_id==merchant_id, Opportunity.status=="open").order_by(Opportunity.priority.desc()).all()
    return all_opps

def score_opportunities(db: Session, merchant_id: str="m_demo"):
    """Objective-aware ranking. Merchant objective selects the value axis:
    revenue -> incremental revenue; margin -> incremental margin;
    clearance -> dead-stock velocity value; retention -> churn/repeat value.
    Risk tolerance scales the risk penalty. Returns sorted opportunities."""
    from ..models.entities import Opportunity
    obj=ensure_merchant_objective(db, merchant_id)
    opps=db.query(Opportunity).filter(Opportunity.merchant_id==merchant_id, Opportunity.status=="open").all()
    risk_scale={"low": 2.0, "medium": 1.0, "high": 0.5}[getattr(obj, "risk_tolerance", "medium")]
    for o in opps:
        prob=o.confidence or 0.0
        exp_margin=o.expected_margin or 0
        exp_rev=o.expected_revenue or 0
        # objective value axis
        if obj.primary_objective == "margin":
            value = exp_margin
        elif obj.primary_objective == "clearance":
            value = exp_margin * 1.2 if o.type == "dead_stock" else exp_margin * 0.7
        elif obj.primary_objective == "retention":
            value = exp_margin * 1.25 if o.type in ("churn_risk", "repeat_purchase", "abandoned_cart") else exp_margin * 0.8
        else:  # revenue
            value = exp_rev * 0.35 + exp_margin * 0.65
        # expected net contribution: value*prob - cost - risk
        cost=int(exp_rev*0.05) if exp_rev else 5000
        risk_pen={"low":0, "medium":5000, "high":15000}[o.risk or "low"] * risk_scale
        score=(value * prob) - cost - risk_pen
        o.priority=round(score/100000,3)  # normalize
        # persist economics trace for the dashboard evidence panel
        ev = dict(o.evidence or {})
        ev["objective"] = obj.primary_objective
        ev["risk_tolerance"] = getattr(obj, "risk_tolerance", "medium")
        ev["value_axis"] = round(value, 2)
        o.evidence = ev
    db.commit()
    return sorted(opps, key=lambda x: x.priority, reverse=True)

def _action_hash(campaign_id: str, discount: int, budget: int, policy_version: int) -> str:
    import hashlib
    return hashlib.sha256(f"{campaign_id}:{discount}:{budget}:{policy_version}".encode()).hexdigest()[:16]


def plan_action(db: Session, opportunity_id: str):
    """Action planner: Opportunity -> Why -> Action -> Audience -> Offer ->
    Economics -> Policy -> Execute. Enforces max discount / min margin /
    budget server-side via check_campaign_policy. Creates an Approval record
    when escalation is required; approval binds merchant + campaign + amount
    + policy version + action hash."""
    from ..models.entities import Opportunity, Campaign, CampaignAudience, CampaignAction, Product, Approval
    from ..trust.policy import check_campaign_policy, get_policy
    from datetime import datetime, timedelta
    import hashlib
    opp=db.query(Opportunity).filter(Opportunity.id==opportunity_id).first()
    if not opp: return None
    obj=ensure_merchant_objective(db, opp.merchant_id)
    # Build audience actual IDs
    seg=opp.target_segment or {}
    cust_ids=seg.get("customer_ids", [])
    count=seg.get("count", len(cust_ids) or 10)
    # Offer: discount capped by merchant max (never exceed)
    discount=min(obj.max_discount, 8 if opp.risk=="low" else 5)
    if opp.type=="dead_stock": discount=min(obj.max_discount, 12)
    if opp.type=="low_margin": discount=0
    # Economics: expected net contribution from learned estimates
    exp_rev=opp.expected_revenue or 0; exp_margin=opp.expected_margin or 0
    budget=int(min(exp_rev*0.1 if exp_rev else 50000, obj.max_campaign_budget))
    cost=int(exp_rev*0.05) if exp_rev else 5000
    # expected margin % on revenue for min-margin gate
    exp_margin_pct=(exp_margin/max(exp_rev,1)*100) if exp_rev else None
    pol=get_policy(db, opp.merchant_id)
    verdict=check_campaign_policy(db, opp.merchant_id, discount, budget, exp_margin_pct)
    decision=verdict["decision"]  # approved | escalated | blocked
    if decision=="blocked":
        return {"opportunity": opp, "campaign": None, "blocked": True,
                "policy": {"ok": False, "decision": "blocked",
                           "reason": verdict["reason"],
                           "violated_rule": verdict.get("violated_rule"),
                           "policy_version": verdict["policy_version"],
                           "limits": verdict.get("limits")},
                "next": "blocked — adjust discount/budget/margin and re-plan"}
    # Create campaign
    camp=Campaign(merchant_id=opp.merchant_id, name=f"{opp.type} — {opp.recommended_action}", target_category=seg.get("segment","general"), discount=discount, trigger_product_id=None, recommend_product_id=opp.recommended_product_id, proposal_reason=f"Type {opp.type}: {opp.evidence} -> {opp.recommended_action}", expected_incremental_paise=exp_rev or 0, expected_incremental_margin=exp_margin or 0, budget_paise=budget, cost_paise=cost, policy_version=verdict["policy_version"], simulation_mode=True, status="proposed" if decision=="escalated" else "approved")
    db.add(camp); db.flush()
    camp.action_hash=_action_hash(camp.id, discount, budget, verdict["policy_version"])
    db.add(CampaignAudience(campaign_id=camp.id, segment=seg.get("segment","targeted"), customer_count=count))
    # store actual customer_ids in payload
    db.add(CampaignAction(campaign_id=camp.id, action_type=opp.type, payload={"opportunity_id": opp.id, "customer_ids": cust_ids, "discount": discount, "budget": budget, "cost": cost, "decision": ("requires_approval" if decision=="escalated" else "auto_approved"), "expected_margin": exp_margin, "expected_revenue": exp_rev, "confidence": opp.confidence, "policy_version": verdict["policy_version"]}))
    approval_id=None
    if decision=="escalated":
        appr=Approval(merchant_id=opp.merchant_id, campaign_id=camp.id, action="execute_campaign", action_type=opp.type, amount=budget, status="pending", requested_by="growth-agent", policy_version=verdict["policy_version"], reason=verdict["reason"], expires_at=datetime.utcnow()+timedelta(days=7))
        db.add(appr); db.flush(); approval_id=appr.id
        camp.approved_amount=budget
    opp.status="proposed"
    db.commit(); db.refresh(camp)
    return {"opportunity": opp, "campaign": camp, "audience_count": count, "customer_ids": cust_ids[:5], "offer": f"{discount}%", "budget_inr": round(budget/100,2), "economics": {"expected_revenue": exp_rev, "expected_margin": exp_margin, "cost": cost, "expected_net": exp_margin - cost, "margin_pct": round(exp_margin_pct,1) if exp_margin_pct is not None else None}, "policy": {"ok": decision=="approved", "decision": ("auto_approved" if decision=="approved" else "requires_approval"), "reason": verdict["reason"], "policy_version": verdict["policy_version"], "approval_id": approval_id}, "next": "approve -> execute -> measure"}

def _assign_experiment(db: Session, camp, customer_ids: list[str], ratio: float):
    """Stable treatment/control assignment: sha256(campaign:customer) % 100.
    Customer stays in the same group once assigned (unique constraint)."""
    import hashlib
    from datetime import datetime
    from ..models.entities import CampaignAudience
    ratio = min(0.5, max(0.01, ratio or 0.10))
    assigned = []
    for cid in customer_ids:
        existing = db.query(CampaignAudience).filter(
            CampaignAudience.campaign_id == camp.id,
            CampaignAudience.customer_id == cid).first()
        if existing:
            assigned.append(existing)
            continue
        h = int(hashlib.sha256(f"{camp.id}:{cid}".encode()).hexdigest(), 16) % 100
        group = "control" if h < int(ratio * 100) else "treatment"
        row = CampaignAudience(campaign_id=camp.id, segment="experiment",
                               customer_count=1, customer_id=cid, group=group,
                               assigned_at=datetime.utcnow(),
                               exposed_at=datetime.utcnow() if group == "treatment" else None,
                               is_simulated=False)
        db.add(row)
        assigned.append(row)
    db.flush()
    return assigned


def record_outcome(db: Session, campaign_id: str, funnel: dict | None = None):
    """Treatment/control measurement from per-customer audience rows + real orders.

    treatment_conversion = treatment_purchases / treatment_eligible
    control_conversion   = control_purchases / control_eligible
    incremental_* is measured against the control baseline scaled to the
    treatment population — never claimed without a control.
    Low samples (either arm < 30 eligible) set sample_adequate=False and the
    caller must not report significant lift.
    """
    import math
    from datetime import datetime
    from ..models.entities import CampaignMetric, Campaign, CampaignAudience, Order, Product
    camp = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not camp:
        return None
    rows = db.query(CampaignAudience).filter(
        CampaignAudience.campaign_id == camp.id,
        CampaignAudience.customer_id.isnot(None)).all()
    sim = bool(getattr(camp, "simulation_mode", True))
    if rows:
        t_rows = [r for r in rows if r.group == "treatment"]
        c_rows = [r for r in rows if r.group == "control"]
        t_elig, c_elig = len(t_rows), len(c_rows)
        t_purch = sum(1 for r in t_rows if r.purchased_at is not None)
        c_purch = sum(1 for r in c_rows if r.purchased_at is not None)
        # revenue/margin from linked orders
        order_ids = [r.order_id for r in rows if r.order_id]
        rev_by_order = {}
        if order_ids:
            for o in db.query(Order).filter(Order.id.in_(order_ids)).all():
                rev_by_order[o.id] = o.total or 0
        # margin needs product cost: use campaign recommended product
        margin_rate = 0.25
        if camp.recommend_product_id:
            prod = db.query(Product).filter(Product.id == camp.recommend_product_id).first()
            if prod and prod.price:
                margin_rate = ((prod.price - (prod.cost_price or int(prod.price * 0.75))) / prod.price)
        t_rev = sum(rev_by_order.get(r.order_id, 0) for r in t_rows if r.order_id)
        c_rev = sum(rev_by_order.get(r.order_id, 0) for r in c_rows if r.order_id)
        t_margin = int(t_rev * margin_rate)
        c_margin = int(c_rev * margin_rate)
        exposed = sum(1 for r in t_rows if r.exposed_at is not None)
    else:
        # legacy aggregate path (pre-experiment campaigns only): control rate
        # is derived from the merchant's own order history, never a fixed 2%.
        from .conversion import cohort_conversion
        funnel = funnel or {}
        eligible = int(funnel.get("eligible", funnel.get("exposed", 0) * 1.1 if funnel.get("exposed") else 100))
        t_elig = int(eligible * 0.9)
        c_elig = eligible - t_elig
        exposed = int(funnel.get("exposed", t_elig))
        t_purch = int(funnel.get("purchased", funnel.get("conversions", 0)))
        t_rev = int(funnel.get("revenue_paise", funnel.get("revenue", 0)))
        try:
            c_rate = cohort_conversion(db, camp.merchant_id, "cross_sell",
                                       camp.target_category)["predicted_conversion"]
        except Exception:
            c_rate = 0.02
        c_purch = int(c_elig * c_rate)
        c_rev = int(c_purch * (t_rev / max(t_purch, 1) if t_purch else 50000))
        t_margin = int(t_rev * 0.25)
        c_margin = int(c_rev * 0.25)
    t_conv = (t_purch / t_elig) if t_elig else 0.0
    c_conv = (c_purch / c_elig) if c_elig else 0.0
    lift = t_conv - c_conv
    # scale control baseline to treatment population
    expected_control_orders = c_conv * t_elig
    expected_control_rev = (c_rev / max(c_elig, 1)) * t_elig if c_elig else 0
    expected_control_margin = (c_margin / max(c_elig, 1)) * t_elig if c_elig else 0
    incr_orders = int(round(t_purch - expected_control_orders))
    incr_rev = int(round(t_rev - expected_control_rev))
    incr_margin = int(round(t_margin - expected_control_margin))
    # per-customer rates
    t_rpc = (t_rev / t_elig) if t_elig else 0
    c_rpc = (c_rev / c_elig) if c_elig else 0
    t_mpc = (t_margin / t_elig) if t_elig else 0
    c_mpc = (c_margin / c_elig) if c_elig else 0
    # Wilson-ish CI on lift via normal approx
    se = math.sqrt(max(0.0, t_conv * (1 - t_conv) / max(t_elig, 1) + c_conv * (1 - c_conv) / max(c_elig, 1)))
    ci = [round(lift - 1.96 * se, 4), round(lift + 1.96 * se, 4)]
    adequate = (t_elig >= 30 and c_elig >= 10)
    met = CampaignMetric(campaign_id=camp.id, impressions=exposed,
                         conversions=t_purch, revenue_paise=t_rev,
                         uplift_paise=incr_rev,
                         treatment_eligible=t_elig, treatment_purchases=t_purch,
                         treatment_revenue=t_rev, treatment_margin=t_margin,
                         control_eligible=c_elig, control_purchases=c_purch,
                         control_revenue=c_rev, control_margin=c_margin,
                         incremental_orders=incr_orders, incremental_revenue=incr_rev,
                         incremental_margin=incr_margin,
                         ci_low=ci[0], ci_high=ci[1],
                         sample_adequate=adequate, simulation_mode=sim)
    db.add(met)
    db.commit()
    db.refresh(met)
    # legacy attribute compat for older callers
    met.incremental_conversions = incr_orders
    met.control_conversions = c_purch
    met.control_revenue = c_rev
    met.uplift_pct = round((incr_rev / max(expected_control_rev, 1) * 100), 1) if expected_control_rev else 0.0
    return met

def execute_campaign(db: Session, campaign_id: str, simulation_mode: bool = True):
    """Campaign execution with explicit experiment arms.

    Steps: eligible audience -> stable treatment/control assignment ->
    exposure (treatment only; control never receives treatment) ->
    observed events -> observed purchases/orders -> measurement.

    simulation_mode=True (demo default): synthesized responses are written to
    per-customer rows flagged is_simulated=True and the metric carries
    simulation_mode=True — the dashboard must label these "Demo simulation",
    never real observed behavior.
    simulation_mode=False (production): only assignment + exposure happen
    here; purchases are recorded later via record_observed_purchase() from
    real order events.
    """
    from datetime import datetime
    from ..models.entities import (Campaign, CampaignAudience, CampaignAction,
                                   Order, Checkout, Cart, CartItem, Product)
    from ..core.events import publish
    camp = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not camp:
        return None
    if camp.status not in ("proposed", "approved", "active"):
        return {"error": f"campaign status {camp.status} not executable"}
    # approval gate: escalated campaigns need a valid bound approval
    if camp.status == "proposed":
        from ..models.entities import Approval
        appr = db.query(Approval).filter(
            Approval.campaign_id == camp.id, Approval.status == "approved").first()
        if not appr:
            return {"error": "campaign requires approval before execute (PROPOSED->APPROVED). Call /approve with X-Approved-By."}
        # verify binding: amount + policy version + action hash unchanged
        if appr.amount != (camp.approved_amount or camp.budget_paise or appr.amount):
            return {"error": "approval amount mismatch — re-approval required"}
        if appr.policy_version != camp.policy_version:
            return {"error": "stale policy version — re-approval required"}
        if camp.action_hash and _action_hash(camp.id, camp.discount or 0, camp.budget_paise or 0, camp.policy_version) != camp.action_hash:
            return {"error": "action mutated after approval — re-approval required"}
        camp.status = "approved"
        db.commit()
    camp.status = "active"
    camp.simulation_mode = simulation_mode
    db.commit()
    act = db.query(CampaignAction).filter(CampaignAction.campaign_id == camp.id).first()
    cust_ids = (act.payload.get("customer_ids") if act and act.payload else []) or []
    if not cust_ids:
        # fall back to merchant customers for demo breadth
        from ..models.entities import Customer
        cust_ids = [c.id for c in db.query(Customer).filter(
            Customer.merchant_id == camp.merchant_id).limit(100).all()]
    assigned = _assign_experiment(db, camp, cust_ids, getattr(camp, "experiment_ratio", 0.10) or 0.10)
    db.commit()
    t_rows = [r for r in assigned if r.group == "treatment"]
    # control never receives treatment: no exposure, no orders
    real_orders: list[str] = []
    if simulation_mode:
        import random
        rng = random.Random(int(camp.id.encode().hex()[:8], 16) % (2 ** 31))
        prod = None
        if camp.recommend_product_id:
            prod = db.query(Product).filter(Product.id == camp.recommend_product_id).first()
        if not prod:
            prod = db.query(Product).filter(Product.merchant_id == camp.merchant_id).first()
        discount = camp.discount or 0
        base_rate = 0.08
        for r in t_rows:
            r.exposed_at = r.exposed_at or datetime.utcnow()
            if rng.random() < base_rate:
                r.viewed_at = datetime.utcnow()
            if r.viewed_at and rng.random() < 0.33:
                r.clicked_at = datetime.utcnow()
            if r.clicked_at and rng.random() < 0.60:
                r.added_at = datetime.utcnow()
            if r.added_at and rng.random() < 0.66:
                r.purchased_at = datetime.utcnow()
                r.is_simulated = True
                if prod:
                    line_total = int(prod.price * (1 - discount / 100))
                    cart = Cart(merchant_id=camp.merchant_id, customer_id=r.customer_id)
                    db.add(cart)
                    db.flush()
                    db.add(CartItem(cart_id=cart.id, product_id=prod.id, quantity=1,
                                    unit_price=prod.price, line_total=line_total))
                    db.flush()
                    chk = Checkout(cart_id=cart.id, merchant_id=camp.merchant_id,
                                   customer_id=r.customer_id, total=line_total,
                                   status="captured")
                    db.add(chk)
                    db.flush()
                    order = Order(checkout_id=chk.id, merchant_id=camp.merchant_id,
                                  customer_id=r.customer_id, campaign_id=camp.id,
                                  total=line_total, status="paid")
                    db.add(order)
                    db.flush()
                    r.order_id = order.id
                    real_orders.append(order.id)
        # control arm: organic baseline purchases (small, simulated, flagged)
        for r in [x for x in assigned if x.group == "control"]:
            if rng.random() < 0.02:
                r.purchased_at = datetime.utcnow()
                r.is_simulated = True
        db.commit()
        try:
            publish("campaign.executed", {"campaign_id": camp.id, "orders": real_orders,
                                          "simulation_mode": True,
                                          "treatment": len(t_rows),
                                          "control": len(assigned) - len(t_rows)})
        except Exception:
            pass
    met = record_outcome(db, camp.id, None)
    camp.status = "completed"
    db.commit()
    t_elig = getattr(met, "treatment_eligible", 0)
    c_elig = getattr(met, "control_eligible", 0)
    funnel = {"eligible": t_elig + c_elig, "exposed": met.impressions,
              "purchased": met.conversions, "revenue_paise": met.revenue_paise,
              "simulation_mode": sim_flag(met)}
    return {"campaign": camp, "funnel": funnel, "metric": met,
            "treatment": {"eligible": t_elig,
                          "purchases": met.treatment_purchases,
                          "conversion": round(met.treatment_purchases / max(t_elig, 1), 4),
                          "revenue": met.treatment_revenue,
                          "margin": met.treatment_margin},
            "control": {"eligible": c_elig,
                        "purchases": met.control_purchases,
                        "conversion": round(met.control_purchases / max(c_elig, 1), 4),
                        "revenue": met.control_revenue,
                        "margin": met.control_margin},
            "incremental_revenue": met.incremental_revenue,
            "incremental_margin": met.incremental_margin,
            "incremental_conversions": met.incremental_orders,
            "sample_adequate": met.sample_adequate,
            "simulation_mode": sim_flag(met),
            "real_orders": real_orders}


def sim_flag(met) -> bool:
    return bool(getattr(met, "simulation_mode", True))


def record_observed_purchase(db: Session, campaign_id: str, customer_id: str,
                             order_id: str, revenue_paise: int):
    """Production path: link a real order to its experiment arm. Control
    purchases count toward baseline; treatment purchases toward treatment."""
    from datetime import datetime
    from ..models.entities import CampaignAudience
    row = db.query(CampaignAudience).filter(
        CampaignAudience.campaign_id == campaign_id,
        CampaignAudience.customer_id == customer_id).first()
    if not row:
        return None
    row.purchased_at = datetime.utcnow()
    row.order_id = order_id
    row.is_simulated = False
    db.commit()
    return row

def learning_update(db: Session, merchant_id: str="m_demo"):
    """Closed learning loop: observed treatment outcomes -> posterior per
    learning key -> persisted LearningState -> consumed by the NEXT
    detect/rank via _learned_or_cohort. Returns prev/observed/updated +
    sample size + CI for every key so the dashboard can show learning."""
    import math
    from datetime import datetime
    from ..models.entities import Campaign, CampaignMetric, CampaignAction, LearningState
    camps = db.query(Campaign).filter(Campaign.merchant_id == merchant_id).all()
    updates = []
    for camp in camps:
        mets = db.query(CampaignMetric).filter(CampaignMetric.campaign_id == camp.id).all()
        if not mets:
            continue
        # only learn from adequate, non-simulated samples; simulated runs
        # update with explicit simulated flag so cold-start isn't polluted silently
        usable = [m for m in mets if m.sample_adequate]
        pool = usable if usable else mets
        t_elig = sum(m.treatment_eligible or 0 for m in pool)
        t_purch = sum(m.treatment_purchases or 0 for m in pool)
        if not t_elig:
            continue
        act = db.query(CampaignAction).filter(CampaignAction.campaign_id == camp.id).first()
        opp_type = (act.action_type if act else "campaign")
        cat = (camp.target_category or "global")
        key = f"{opp_type}:{cat}"
        ls = db.query(LearningState).filter(
            LearningState.merchant_id == merchant_id, LearningState.key == key).first()
        if not ls:
            ls = LearningState(merchant_id=merchant_id, key=key)
            db.add(ls)
            db.flush()
        prev = ls.mean
        # Beta-Binomial posterior: prior Beta(2,2) + all observed trials
        alpha = 2 + (ls.successes or 0) + t_purch
        beta = 2 + (ls.observations or 0) - (ls.successes or 0) + (t_elig - t_purch)
        mean = alpha / (alpha + beta)
        var = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1))
        se = math.sqrt(max(0.0, var))
        ls.prev_mean = prev
        ls.alpha = alpha
        ls.beta = beta
        ls.observations = (ls.observations or 0) + t_elig
        ls.successes = (ls.successes or 0) + t_purch
        ls.mean = round(mean, 4)
        ls.ci_low = round(max(0.0, mean - 1.96 * se), 4)
        ls.ci_high = round(min(1.0, mean + 1.96 * se), 4)
        ls.source = "simulated" if all(getattr(m, "simulation_mode", True) for m in pool) else "observed"
        ls.updated_at = datetime.utcnow()
        # also refresh the linked opportunity confidence so re-runs rank higher
        opp_id = act.payload.get("opportunity_id") if act and act.payload else None
        if opp_id:
            from ..models.entities import Opportunity
            opp = db.query(Opportunity).filter(Opportunity.id == opp_id).first()
            if opp:
                old = opp.confidence
                opp.confidence = round(0.5 * (old or 0) + 0.5 * mean, 3)
                ev = dict(opp.evidence or {})
                ev.update({"observations": t_elig, "successes": t_purch,
                           "posterior_alpha": round(alpha, 2),
                           "posterior_beta": round(beta, 2),
                           "ci_95": [ls.ci_low, ls.ci_high],
                           "learned_key": key})
                opp.evidence = ev
        updates.append({"key": key, "opportunity": opp_id,
                        "previous_estimate": round(prev or 0.08, 4),
                        "observed_conversion": round(t_purch / max(t_elig, 1), 4),
                        "updated_estimate": round(mean, 4),
                        "sample_size": t_elig,
                        "ci": [ls.ci_low, ls.ci_high],
                        "source": ls.source})
    db.commit()
    return updates

def run_autonomous_cycle(db: Session, merchant_id: str="m_demo"):
    """Autonomous: Observe -> detect -> rank -> decide -> authorize -> execute -> measure -> learn (Phase 10 full loop)"""
    # Detect
    opps=detect_opportunities(db, merchant_id)
    scored=score_opportunities(db, merchant_id)
    if not scored:
        return {"opportunities": [], "top": None, "action": None}
    top=scored[0]
    planned=plan_action(db, top.id)
    # Phase 10: policy -> execute -> measure if auto_approved
    executed=None
    measured=None
    if planned and planned["policy"]["decision"]=="auto_approved":
        camp=planned["campaign"]
        # authorize and execute
        exec_res=execute_campaign(db, camp.id)
        if exec_res and "metric" in exec_res:
            executed={"campaign_id": camp.id, "status": exec_res["campaign"].status, "funnel": exec_res["funnel"]}
            measured={"revenue_inr": round((exec_res["metric"].revenue_paise or 0)/100,2), "uplift_inr": round((exec_res["metric"].uplift_paise or 0)/100,2)}
    # learn step
    learning=learning_update(db, merchant_id)
    return {"opportunities": [{"id": o.id, "type": o.type, "priority": o.priority, "expected_inr": round((o.expected_revenue or 0)/100,2)} for o in scored[:7]], "top": {"id": top.id, "type": top.type, "priority": top.priority, "expected_revenue_inr": round((top.expected_revenue or 0)/100,2), "expected_margin_inr": round((top.expected_margin or 0)/100,2), "confidence": top.confidence, "risk": top.risk}, "planned": planned, "executed": executed, "measured": measured, "learning_updates": len(learning)}
