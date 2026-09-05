"""
Deterministic demo scenario (item 41): profitable-growth merchant, medium
risk, capped discount/budget -> MAG inspects history, finds evidence-backed
opportunity, checks policy, executes with treatment/control, measures
incremental lift + margin, updates learning, re-runs with changed estimate.
Also shows one high-risk action escalated -> bound approval -> execution.

Run: python scripts/demo_scenario.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "backend", "tests"))

from test_mag95_closed_loop import _fresh_db, _seed, _close


def main():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.models.entities import MerchantObjective
    obj = db.query(MerchantObjective).filter_by(merchant_id="m_eval1").first()
    obj.primary_objective = "margin"
    obj.risk_tolerance = "medium"
    obj.min_margin_pct = 10
    obj.max_discount = 10
    obj.max_campaign_budget = 1000000
    db.commit()
    print("OBJECTIVE: maximize margin | risk=medium | min_margin=10% | max_disc=10% | budget=10000.00 INR")

    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities,
                                                plan_action,
                                                execute_campaign,
                                                learning_update,
                                                _learned_or_cohort)
    opps = detect_opportunities(db, "m_eval1")
    scored = score_opportunities(db, "m_eval1")
    top = scored[0]
    ev = top.evidence or {}
    print(f"\n1-3. MAG inspected history -> {len(scored)} opportunities. TOP: {top.type}")
    print(f"   EVIDENCE: conv={ev.get('conv')} source={ev.get('conv_source')} n={ev.get('conv_sample')} "
          f"affinity={ev.get('affinity')} margin_est={ev.get('margin_estimated')}")
    print(f"   ECONOMICS: rev={top.expected_revenue} margin={top.expected_margin} conf={top.confidence} risk={top.risk}")

    planned = plan_action(db, top.id)
    camp = planned["campaign"]
    print(f"4-5. POLICY: {planned['policy']['decision']} — {planned['policy'].get('reason')}")
    before = _learned_or_cohort(db, "m_eval1", f"{top.type}:shoes", top.type, "shoes")
    print(f"   LEARNED-BEFORE: {before}")

    if planned["policy"]["decision"] == "requires_approval":
        from datetime import datetime
        from app.models.entities import Approval
        appr = db.query(Approval).filter(Approval.campaign_id == camp.id).first()
        appr.status = "approved"
        appr.approved_by = "demo-merchant"
        appr.decided_at = datetime.utcnow()
        camp.status = "approved"
        db.commit()
        print(f"6-8. ESCALATED -> human approved (binding: amount={appr.amount} policy_v={appr.policy_version}) -> executing")
    else:
        camp.status = "approved"
        db.commit()
        print("6-8. AUTO-APPROVED within limits -> executing")

    res = execute_campaign(db, camp.id, simulation_mode=True)
    met = res["metric"]
    print(f"9-13. OUTCOME [Demo simulation]: T={res['treatment']['purchases']}/{res['treatment']['eligible']} "
          f"({res['treatment']['conversion']}) vs C={res['control']['purchases']}/{res['control']['eligible']} "
          f"({res['control']['conversion']})")
    print(f"   INCREMENTAL: orders={met.incremental_orders} rev={met.incremental_revenue} "
          f"margin={met.incremental_margin} adequate={met.sample_adequate} CI=[{met.ci_low},{met.ci_high}]")

    ups = learning_update(db, "m_eval1")
    print(f"14. LEARNING: {ups[0]['previous_estimate']} -> observed {ups[0]['observed_conversion']} "
          f"-> updated {ups[0]['updated_estimate']} (n={ups[0]['sample_size']})")

    opps2 = detect_opportunities(db, "m_eval1")
    scored2 = score_opportunities(db, "m_eval1")
    print(f"15-16. RE-RUN: {len(scored2)} opportunities; top now {scored2[0].type} "
          f"(evidence carries learned posterior)")

    # high-risk action demo: discount far above max -> blocked server-side
    from app.trust.policy import check_campaign_policy
    v = check_campaign_policy(db, "m_eval1", discount=25, budget=50000, expected_margin_pct=40.0)
    print(f"\nHIGH-RISK DEMO: 25% discount -> {v['decision']} ({v['reason']}) violated={v['violated_rule']}")

    db.close()
    _close(Session)
    print("\nDEMO COMPLETE")


if __name__ == "__main__":
    main()
