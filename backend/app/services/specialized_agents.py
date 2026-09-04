
"""P1-19 agent specialization: Revenue, Retention, Inventory, Decision"""
def revenue_agent(opportunities):
    # prefers high expected_revenue
    return sorted(opportunities, key=lambda o: o.expected_revenue or 0, reverse=True)[0] if opportunities else None
def retention_agent(opportunities, customers):
    # prefers churn_risk / high churn
    churn=[o for o in opportunities if o.type=="churn_risk"]
    return churn[0] if churn else None
def inventory_agent(opportunities):
    dead=[o for o in opportunities if o.type in ["dead_stock","stock_risk"]]
    return dead[0] if dead else None
def decision_agent(revenue_pick, retention_pick, inventory_pick, merchant_objective):
    # P1-13 multi-objective decision: compare options A/B/C
    obj=merchant_objective.primary_objective if merchant_objective else "revenue"
    if obj=="margin":
        # prefer retention/high_margin
        return retention_pick or revenue_pick
    if obj=="clearance":
        return inventory_pick or revenue_pick
    return revenue_pick

def compare_options(opportunities, objective):
    """P1-13 Multi-objective: build Option A/B/C with revenue/margin tradeoff"""
    opts=[]
    for o in opportunities[:3]:
        rev=(o.expected_revenue or 0)/100
        marg=(o.expected_margin or 0)/100
        opts.append({"option": o.type, "opportunity_id": o.id, "revenue": rev, "margin": marg, "confidence": o.confidence, "risk": o.risk})
    # choose based on objective
    if objective=="margin":
        chosen=max(opts, key=lambda x: x["margin"]) if opts else None
    elif objective=="clearance":
        chosen=[o for o in opts if "stock" in o["option"]][0] if any("stock" in o["option"] for o in opts) else (opts[0] if opts else None)
    else:
        chosen=max(opts, key=lambda x: x["revenue"]) if opts else None
    return {"options": opts, "chosen": chosen, "objective": objective}
