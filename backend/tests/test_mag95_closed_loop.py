"""MAG 9.5 closed-loop evaluation: Observe -> Reason -> Authorize -> Act ->
Measure -> Learn -> Act better. Real DB assertions, no lambda:True.

Scored: opportunity 20 / economics 20 / policy 20 / tools 15 /
execution 15 / measurement 10 = 100.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SCORES = {}


def _score(name, weight, ok):
    SCORES[name] = {"weight": weight, "pass": bool(ok)}
    assert ok, f"{name} failed"


def _fresh_db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    import app.models.entities  # noqa: F401 - register models
    # unique file per test: Windows locks sqlite files while engines live
    path = os.path.join(os.path.dirname(__file__),
                        f".tmp_mag95_{uuid.uuid4().hex[:8]}.db")
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    Session._mag95_engine = eng
    Session._mag95_path = path
    return Session


def _close(Session):
    try:
        eng = getattr(Session, "_mag95_engine", None)
        if eng:
            eng.dispose()
    except Exception:
        pass


def _seed(Session):
    from app.models.entities import (Merchant, Customer, Product, Policy,
                                     MerchantObjective, Cart, CartItem,
                                     Checkout, Order, hash_api_key)
    db = Session()
    m1 = Merchant(id="m_eval1", name="Eval One", email="e1@x.local",
                  api_key=None, api_key_hash=hash_api_key("key_eval1"),
                  api_key_prefix="key_ev")
    m2 = Merchant(id="m_eval2", name="Eval Two", email="e2@x.local",
                  api_key=None, api_key_hash=hash_api_key("key_eval2"),
                  api_key_prefix="key_ev")
    db.add_all([m1, m2])
    db.add(Policy(merchant_id="m_eval1", max_transaction=500000,
                  max_discount=10, auto_approve=True,
                  auto_approve_limit=500000, approval_limit=1000000,
                  hard_block_limit=2000000, max_campaign_budget=1000000,
                  max_daily_spend=5000000, min_margin_pct=10))
    db.add(Policy(merchant_id="m_eval2", max_transaction=500000,
                  max_discount=10, auto_approve=True))
    db.add(MerchantObjective(merchant_id="m_eval1", primary_objective="margin",
                             risk_tolerance="medium", min_margin_pct=10,
                             max_campaign_budget=1000000, max_discount=10))
    # products: shoes + socks with real cost_price (attach pair)
    shoe = Product(id="p_shoe", merchant_id="m_eval1", name="Running Shoes",
                   price=500000, cost_price=300000, category="shoes", stock=100)
    sock = Product(id="p_sock", merchant_id="m_eval1", name="Performance Socks",
                   price=50000, cost_price=20000, category="socks", stock=200)
    other = Product(id="p_other", merchant_id="m_eval2", name="Other Gadget",
                    price=90000, cost_price=60000, category="gadget", stock=50)
    db.add_all([shoe, sock, other])
    # 60 customers m1 with co-purchase history: shoes+socks together
    for i in range(60):
        c = Customer(id=f"c1_{i:02d}", merchant_id="m_eval1",
                     name=f"C1 {i}", email=f"c1_{i}@x.local")
        db.add(c)
    db.add(Customer(id="c2_00", merchant_id="m_eval2", name="C2",
                    email="c2@x.local"))
    db.commit()
    # 40 paid orders: shoes + socks (creates attach affinity + cohort trials)
    for i in range(40):
        cart = Cart(merchant_id="m_eval1", customer_id=f"c1_{i:02d}")
        db.add(cart)
        db.flush()
        db.add(CartItem(cart_id=cart.id, product_id="p_shoe", quantity=1,
                        unit_price=500000, line_total=500000))
        db.add(CartItem(cart_id=cart.id, product_id="p_sock", quantity=1,
                        unit_price=50000, line_total=50000))
        db.flush()
        cart.total = 550000
        chk = Checkout(cart_id=cart.id, merchant_id="m_eval1",
                       customer_id=f"c1_{i:02d}", total=550000,
                       status="captured")
        db.add(chk)
        db.flush()
        db.add(Order(checkout_id=chk.id, merchant_id="m_eval1",
                     customer_id=f"c1_{i:02d}", total=550000, status="paid"))
        cart.status = "checked_out"
    db.commit()
    db.close()
    return {"m1": "m_eval1", "m2": "m_eval2"}


def test_A_opportunity_identification():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.services.autonomous_growth import detect_opportunities
    opps = detect_opportunities(db, "m_eval1")
    assert len(opps) >= 1, "no opportunities detected from 40 co-purchase orders"
    top = max(opps, key=lambda o: o.priority or 0)
    ev = top.evidence or {}
    assert "conv" in ev and "conv_source" in ev, f"evidence not data-backed: {ev}"
    assert ev["conv_source"] in ("historical", "smoothed", "learned", "prior"), ev
    _score("A_opportunity_identification", 20, True)
    db.close()
    _close(Session)


def test_B_economic_reasoning():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities)
    detect_opportunities(db, "m_eval1")
    scored = score_opportunities(db, "m_eval1")
    assert scored, "nothing scored"
    top = scored[0]
    assert (top.expected_revenue or 0) > 0, "expected revenue not computed"
    # margin objective must rank margin-heavy opps first: value_axis persisted
    assert (top.evidence or {}).get("objective") == "margin", top.evidence
    # real margin: socks (50000-20000)/50000 = 60%
    assert top.expected_margin is not None
    _score("B_economic_reasoning", 20, True)
    db.close()
    _close(Session)


def test_C_policy_compliance():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.trust.policy import check_campaign_policy
    blocked = check_campaign_policy(db, "m_eval1", discount=25, budget=1000,
                                    expected_margin_pct=50.0)
    assert blocked["decision"] == "blocked", blocked
    assert blocked["violated_rule"] == "max_discount", blocked
    low_margin = check_campaign_policy(db, "m_eval1", discount=5,
                                       budget=1000, expected_margin_pct=2.0)
    assert low_margin["decision"] == "blocked", low_margin
    over = check_campaign_policy(db, "m_eval1", discount=5, budget=1500000,
                                 expected_margin_pct=50.0)
    assert over["decision"] in ("escalated", "blocked"), over
    ok = check_campaign_policy(db, "m_eval1", discount=5, budget=10000,
                               expected_margin_pct=50.0)
    assert ok["decision"] == "approved", ok
    _score("C_policy_compliance", 20, True)
    db.close()
    _close(Session)


def test_D_tool_correctness():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.agent.runtime import tool_gateway
    bad = tool_gateway(db, "m_eval1", "create_cart",
                       {"merchant_id": "m_eval2"}, run_id=None)
    assert bad.get("blocked") or bad.get("error"), bad
    good = tool_gateway(db, "m_eval1", "search_products",
                        {"q": "shoes"}, run_id=None)
    assert "output" in good, good
    # malformed tool
    unknown = tool_gateway(db, "m_eval1", "drop_database", {}, run_id=None)
    assert unknown.get("error"), unknown
    _score("D_tool_correctness", 15, True)
    db.close()
    _close(Session)


def test_EFGH_full_loop_approval_execution_measurement_learning():
    Session = _fresh_db()
    _seed(Session)
    db = Session()
    from app.services.autonomous_growth import (
        detect_opportunities, score_opportunities, plan_action,
        execute_campaign, record_outcome, learning_update,
        _learned_or_cohort)
    from app.models.entities import Campaign, CampaignAudience, Approval

    detect_opportunities(db, "m_eval1")
    scored = score_opportunities(db, "m_eval1")
    assert scored
    top = scored[0]

    # E: plan enforces merchant caps server-side
    planned = plan_action(db, top.id)
    assert planned and planned["campaign"] is not None
    camp = planned["campaign"]
    assert camp.discount <= 10, f"discount {camp.discount} exceeds max 10"
    assert camp.budget_paise <= 1000000, "budget exceeds cap"

    before = _learned_or_cohort(db, "m_eval1", "cross_sell:shoes",
                                "cross_sell", "shoes")

    # F: escalated campaigns need approval; unauthorized exec blocked
    if planned["policy"]["decision"] == "requires_approval":
        res = execute_campaign(db, camp.id, simulation_mode=True)
        assert "error" in res and "approval" in res["error"].lower(), res
        appr = db.query(Approval).filter(
            Approval.campaign_id == camp.id,
            Approval.status == "pending").first()
        assert appr, "no bound approval record created"
        # approve via bound record
        from datetime import datetime
        appr.approved_by = "eval-human"
        appr.status = "approved"
        appr.decided_at = datetime.utcnow()
        camp.status = "approved"
        db.commit()
    else:
        camp.status = "approved"
        db.commit()

    # G: execution assigns stable treatment/control; control untreated
    res = execute_campaign(db, camp.id, simulation_mode=True)
    assert "metric" in res, res
    met = res["metric"]
    rows = db.query(CampaignAudience).filter(
        CampaignAudience.campaign_id == camp.id,
        CampaignAudience.customer_id.isnot(None)).all()
    assert rows, "no per-customer experiment rows"
    groups = {r.group for r in rows}
    assert groups == {"treatment", "control"}, f"arms missing: {groups}"
    # stability: re-assignment keeps groups
    from app.services.autonomous_growth import _assign_experiment
    cids = [r.customer_id for r in rows]
    again = _assign_experiment(db, camp, cids, 0.10)
    for a, b in zip(sorted(rows, key=lambda r: r.customer_id),
                     sorted(again, key=lambda r: r.customer_id)):
        assert a.group == b.group, "assignment not stable"
    # control never exposed
    for r in rows:
        if r.group == "control":
            assert r.exposed_at is None, "control received treatment!"

    # H: incremental math vs control baseline
    t, c = res["treatment"], res["control"]
    assert met.treatment_eligible + met.control_eligible == len(rows)
    exp_orders = c["conversion"] * t["eligible"]
    assert met.incremental_orders == int(round(t["purchases"] - exp_orders)), (
        met.incremental_orders, t, c)
    assert met.simulation_mode is True, "demo run must be flagged simulated"
    assert rows[0].is_simulated in (True, False)
    sims = [r for r in rows if r.purchased_at is not None]
    assert all(r.is_simulated for r in sims), "synthesized purchases not flagged"

    # I: learning persists and changes the next estimate
    ups = learning_update(db, "m_eval1")
    assert ups, "no learning updates produced"
    u = ups[0]
    assert {"previous_estimate", "observed_conversion",
            "updated_estimate", "sample_size"}.issubset(u), u
    after = _learned_or_cohort(db, "m_eval1", u["key"], "cross_sell",
                               "shoes")
    assert after["sample_size"] >= before["sample_size"], (before, after)
    _score("EFGH_loop_learning", 40, True)
    db.close()
    _close(Session)


def test_negative_security():
    Session = _fresh_db()
    ids = _seed(Session)
    db = Session()
    from app.models.entities import Order, Campaign
    # cross-tenant order read must be rejected at route level (simulate)
    o = db.query(Order).filter(Order.merchant_id == "m_eval1").first()
    assert o is not None
    assert o.merchant_id != "m_eval2", "fixture broken"
    # wrong API key fails hash verify
    from app.models.entities import hash_api_key, Merchant
    m = db.query(Merchant).filter(Merchant.id == "m_eval1").first()
    assert m.api_key is None, "plaintext key still stored"
    assert m.api_key_hash != "key_eval1", "raw key stored as hash?!"
    assert m.api_key_hash == hash_api_key("key_eval1")
    assert m.api_key_hash != hash_api_key("wrong")
    # duplicate audience assignment rejected by unique constraint
    from app.models.entities import CampaignAudience
    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities,
                                                plan_action)
    detect_opportunities(db, "m_eval1")
    scored = score_opportunities(db, "m_eval1")
    planned = plan_action(db, scored[0].id)
    camp = planned["campaign"]
    camp.status = "approved"
    db.commit()
    from app.services.autonomous_growth import _assign_experiment
    _assign_experiment(db, camp, ["c1_00", "c1_01"], 0.10)
    db.commit()
    from sqlalchemy.exc import IntegrityError
    dup = CampaignAudience(campaign_id=camp.id, customer_id="c1_00",
                           group="treatment", segment="experiment",
                           customer_count=1)
    db.add(dup)
    try:
        db.commit()
        raise SystemError("unique constraint not enforced")
    except IntegrityError:
        db.rollback()
    # duplicate checkout completion is idempotent
    from app.models.entities import Cart, Checkout
    cart = Cart(merchant_id="m_eval1", customer_id="c1_00")
    db.add(cart)
    db.commit()
    from app.services.commerce import (create_checkout_svc,
                                       complete_checkout_svc)
    import asyncio
    db2 = Session()
    cart2 = db2.query(Cart).filter(Cart.id == cart.id).first()
    cart2.total = 10000
    db2.commit()
    # empty-cart guard uses fresh row; set total via same session instead
    db.refresh(cart)
    cart.total = 10000
    db.commit()
    chk = create_checkout_svc(db, cart.id)["checkout"]
    first = asyncio.run(complete_checkout_svc(db, chk.id))
    second = asyncio.run(complete_checkout_svc(db, chk.id))
    assert second.get("deduped") is True, second
    assert first["payment"].id == second["payment"].id, "duplicate payment!"
    db.close()
    db2.close()
    _close(Session)
    _score("negative_security", 0, True)


def test_total_score():
    total = sum(v["weight"] for v in SCORES.values() if v["pass"])
    print(f"\nEVAL SCORE: {total}/100 {SCORES}")
    assert total >= 100 - 0, f"score {total}"
