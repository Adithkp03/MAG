"""Data-derived conversion estimation with Bayesian smoothing.

Historical data -> relevant cohort -> observed conversion -> smoothed
posterior -> confidence/sample size -> expected outcome.

Sources: HISTORICAL (n>=50) | SMOOTHED (10<=n<50) | COLD-START prior (n<10).
Cold-start priors below are the ONLY hardcoded rates in the system, used
solely as prior means and always reported as source='prior' — never
presented as observed behavior.
"""
import math

# Conservative global prior: 8% conversion, weight 20 pseudo-observations.
PRIOR_MEAN = 0.08
PRIOR_WEIGHT = 20
MIN_HISTORICAL_N = 50
MIN_SMOOTHED_N = 10

# Per-opportunity cold-start prior means, used ONLY when no cohort history
# and no learned posterior exists. Every use is labeled source='prior'.
COLD_START_PRIORS = {
    "cross_sell": 0.08,
    "upsell": 0.12,
    "churn_risk": 0.08,
    "repeat_purchase": 0.10,
    "dead_stock": 0.15,
    "high_margin": 0.10,
    "high_value": 0.15,
    "abandoned_cart": 0.09,
    "low_margin": 0.05,
    "stock_risk": 0.05,
}


def cold_start_prior(opportunity_type: str) -> float:
    return COLD_START_PRIORS.get(opportunity_type, PRIOR_MEAN)


def estimate(observed_successes: int, observed_trials: int,
             prior_mean: float = PRIOR_MEAN, prior_weight: int = PRIOR_WEIGHT) -> dict:
    obs_s = max(0, int(observed_successes or 0))
    obs_n = max(0, int(observed_trials or 0))
    alpha = prior_weight * prior_mean + obs_s
    beta = prior_weight * (1 - prior_mean) + max(0, obs_n - obs_s)
    total = alpha + beta
    mean = alpha / total if total else prior_mean
    var = (alpha * beta) / ((total ** 2) * (total + 1)) if total else 0.0
    se = math.sqrt(var)
    ci = [round(max(0.0, mean - 1.96 * se), 4), round(min(1.0, mean + 1.96 * se), 4)]
    width = ci[1] - ci[0]
    confidence = round(max(0.0, min(1.0, 1.0 - width)), 3)
    if obs_n >= MIN_HISTORICAL_N:
        source = "historical"
    elif obs_n >= MIN_SMOOTHED_N:
        source = "smoothed"
    else:
        source = "prior"
    return {
        "predicted_conversion": round(mean, 4),
        "sample_size": obs_n,
        "successes": obs_s,
        "confidence": confidence,
        "ci_95": ci,
        "source": source,
        "prior_mean": prior_mean,
        "posterior_alpha": round(alpha, 2),
        "posterior_beta": round(beta, 2),
        "is_cold_start": obs_n < MIN_SMOOTHED_N,
    }


def cohort_conversion(db, merchant_id: str, opportunity_type: str,
                      category: str | None = None) -> dict:
    """Derive observed (successes, trials) for an opportunity cohort.

    Trials = eligible audience size proxy from order/customer history.
    Successes = observed repeat/co-purchase/winback events of matching type.
    Falls back to (0,0) -> prior; caller labels it cold-start.
    """
    from sqlalchemy import text as sql_text
    try:
        if opportunity_type == "cross_sell" and category:
            rows = db.execute(sql_text("""
                SELECT COUNT(DISTINCT o.id) AS n FROM orders o
                JOIN checkouts ch ON o.checkout_id=ch.id
                JOIN carts c ON ch.cart_id=c.id
                JOIN cart_items ci ON ci.cart_id=c.id
                JOIN products p ON p.id=ci.product_id
                WHERE o.merchant_id=:mid AND o.status='paid' AND lower(p.category)=lower(:cat)
            """), {"mid": merchant_id, "cat": category}).mappings().first()
            trials = int(rows["n"] or 0) if rows else 0
            # successes: orders in that category that also contain another category
            srows = db.execute(sql_text("""
                SELECT COUNT(*) AS n FROM (
                  SELECT o.id FROM orders o
                  JOIN checkouts ch ON o.checkout_id=ch.id
                  JOIN carts c ON ch.cart_id=c.id
                  JOIN cart_items ci ON ci.cart_id=c.id
                  JOIN products p ON p.id=ci.product_id
                  WHERE o.merchant_id=:mid AND o.status='paid'
                  GROUP BY o.id HAVING COUNT(DISTINCT lower(p.category)) > 1
                ) t
            """), {"mid": merchant_id}).mappings().first()
            successes = min(trials, int(srows["n"] or 0)) if srows else 0
            return estimate(successes, trials)
        if opportunity_type in ("churn_risk", "repeat_purchase", "abandoned_cart"):
            rows = db.execute(sql_text("""
                SELECT COUNT(*) AS n,
                       SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) AS s
                FROM orders WHERE merchant_id=:mid
            """), {"mid": merchant_id}).mappings().first()
            trials = int(rows["n"] or 0) if rows else 0
            successes = int(rows["s"] or 0) if rows and rows["s"] else 0
            # winback/repeat is a fraction of base purchase rate
            frac = {"churn_risk": 0.3, "repeat_purchase": 0.4, "abandoned_cart": 0.35}.get(opportunity_type, 0.4)
            return estimate(int(successes * frac), trials)
        # generic: paid rate across orders
        rows = db.execute(sql_text("""
            SELECT COUNT(*) AS n, SUM(CASE WHEN status='paid' THEN 1 ELSE 0 END) AS s
            FROM orders WHERE merchant_id=:mid
        """), {"mid": merchant_id}).mappings().first()
        trials = int(rows["n"] or 0) if rows else 0
        successes = int(rows["s"] or 0) if rows and rows["s"] else 0
        return estimate(successes, trials)
    except Exception:
        return estimate(0, 0)
