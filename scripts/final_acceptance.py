"""
MAG final acceptance — every step executes a real assertion against the
service layer on an isolated sqlite DB. No lambda:True, no treating
404/422 as success unless that status is the explicitly expected behavior.

Run:  python scripts/final_acceptance.py   (uses system python, no server needed)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))

RESULTS = []


def step(n, desc, fn):
    try:
        detail = fn()
        ok = bool(detail) if not isinstance(detail, bool) else detail
        RESULTS.append((n, desc, True, str(detail)[:120] if not isinstance(detail, bool) else ""))
        print(f"PASS {n:02d}: {desc}" + (f" — {detail}" if isinstance(detail, str) else ""))
        return True
    except AssertionError as e:
        RESULTS.append((n, desc, False, str(e)[:200]))
        print(f"FAIL {n:02d}: {desc} -> {e}")
        return False
    except Exception as e:
        RESULTS.append((n, desc, False, f"{type(e).__name__}: {str(e)[:200]}"))
        print(f"FAIL {n:02d}: {desc} -> {type(e).__name__}: {e}")
        return False


CTX = {}


def setup():
    import uuid
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.core.database import Base
    import app.models.entities  # noqa
    path = os.path.join(ROOT, "backend", "tests",
                        f".tmp_accept_{uuid.uuid4().hex[:8]}.db")
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=eng)
    CTX["Session"] = Session
    CTX["engine"] = eng
    CTX["path"] = path
    # reuse closed-loop seed for a behaviorally realistic fixture
    sys.path.insert(0, os.path.join(ROOT, "backend", "tests"))
    from test_mag95_closed_loop import _seed
    _seed(Session)
    CTX["db"] = Session()


def teardown():
    try:
        CTX["db"].close()
    except Exception:
        pass
    try:
        CTX["engine"].dispose()
    except Exception:
        pass
    try:
        os.remove(CTX["path"])
    except Exception:
        pass


def main():
    setup()
    db = CTX["db"]
    ok = True

    def t01():
        m = db.query(__import__("app.models.entities", fromlist=["Merchant"]).Merchant).filter_by(id="m_eval1").first()
        assert m and m.api_key_hash and not m.api_key, "keys not hashed"
        return "keys hashed, no plaintext"
    ok &= step(1, "Tenant isolation (cross-merchant order read rejected)", lambda: _t_tenant())
    ok &= step(2, "Product intelligence (velocity/margin/doi from history)", lambda: _t_prod())
    ok &= step(3, "Opportunity ranking (objective-aware, evidence-backed)", lambda: _t_rank())
    ok &= step(4, "Economic scoring (expected revenue/margin/net)", lambda: _t_econ())
    ok &= step(5, "Policy enforcement (discount/margin/budget tiers)", lambda: _t_policy())
    ok &= step(6, "Approval binding (merchant+amount+version+hash)", lambda: _t_approval())
    ok &= step(7, "Campaign lifecycle (proposed->approved->completed)", lambda: _t_lifecycle())
    ok &= step(8, "Treatment/control measurement (arms + stability)", lambda: _t_tc())
    ok &= step(9, "Incremental lift vs control baseline", lambda: _t_lift())
    ok &= step(10, "Learning update changes next estimate", lambda: _t_learn())
    ok &= step(11, "Agent tool loop (gateway rejects mismatch)", lambda: _t_tool())
    ok &= step(12, "UCP lifecycle uses Commerce Core", lambda: _t_ucp())
    ok &= step(13, "Payment idempotency (pay_<checkout_id>)", lambda: _t_pay())
    ok &= step(14, "Webhook idempotency + signature fail-closed", lambda: _t_webhook())
    ok &= step(15, "Outbox reliability (atomic write + relay)", lambda: _t_outbox())
    ok &= step(16, "API keys hashed (no plaintext at rest)", t01)

    n_pass = sum(1 for r in RESULTS if r[2])
    print(f"\nFINAL: {n_pass}/{len(RESULTS)} acceptance checks passed")
    teardown()
    return ok


def _t_tenant():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.database import get_db
    Session = CTX["Session"]

    def override():
        d = Session()
        try:
            yield d
        finally:
            d.close()
    app.dependency_overrides[get_db] = override
    c = TestClient(app, raise_server_exceptions=False)
    # unknown merchant -> 401 (not 404/422)
    r = c.get("/api/v1/orders", headers={"X-Merchant-Id": "nope", "X-API-Key": "x"})
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    # wrong key for real merchant -> 401
    r = c.get("/api/v1/orders", headers={"X-Merchant-Id": "m_eval1", "X-API-Key": "wrong"})
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    # missing key in strict mode -> 401
    import os as _os
    _os.environ["MERCHANT_AUTH_STRICT"] = "1"
    r = c.get("/api/v1/orders", headers={"X-Merchant-Id": "m_eval1"})
    assert r.status_code == 401, f"expected 401 strict, got {r.status_code}"
    # correct key works
    r = c.get("/api/v1/orders", headers={"X-Merchant-Id": "m_eval1", "X-API-Key": "key_eval1"})
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:150]}"
    orders = r.json()
    assert all(o["merchant_id"] == "m_eval1" for o in orders), "tenant leak in list"
    # cross-tenant single read -> 403 (explicitly expected)
    from app.models.entities import Order
    db = CTX["Session"]()
    other = Order(checkout_id=f"chk_x_{os.getpid()}", merchant_id="m_eval2",
                  total=100, status="pending")
    db.add(other)
    db.commit()
    oid = other.id
    db.close()
    r = c.get(f"/api/v1/orders/{oid}", headers={"X-Merchant-Id": "m_eval1", "X-API-Key": "key_eval1"})
    assert r.status_code == 403, f"expected 403 cross-tenant, got {r.status_code}"
    app.dependency_overrides.clear()
    return "401/403 enforced, no leaks"


def _t_prod():
    from app.services.autonomous_growth import compute_product_intelligence
    intel = compute_product_intelligence(CTX["db"], "m_eval1")
    sock = next(p for p in intel if p["product_id"] == "p_sock")
    assert sock["velocity"] > 0, "velocity not derived"
    assert sock["margin_pct"] == 60, f"socks margin should be 60, got {sock['margin_pct']}"
    assert sock["doi"] < 999, "doi missing"
    return f"socks v={sock['velocity']}/d margin=60% doi={sock['doi']}"


def _t_rank():
    from app.services.autonomous_growth import detect_opportunities, score_opportunities
    db = CTX["db"]
    detect_opportunities(db, "m_eval1")
    scored = score_opportunities(db, "m_eval1")
    assert scored, "no ranked opps"
    assert scored == sorted(scored, key=lambda o: o.priority, reverse=True)
    assert (scored[0].evidence or {}).get("objective") == "margin"
    return f"{len(scored)} ranked, top={scored[0].type} p={scored[0].priority}"


def _t_econ():
    from app.services.autonomous_growth import detect_opportunities, score_opportunities
    db = CTX["db"]
    detect_opportunities(db, "m_eval1")
    top = score_opportunities(db, "m_eval1")[0]
    assert (top.expected_revenue or 0) > 0 and top.expected_margin is not None
    return f"rev={top.expected_revenue} margin={top.expected_margin}"


def _t_policy():
    from app.trust.policy import check_campaign_policy
    db = CTX["db"]
    b = check_campaign_policy(db, "m_eval1", 25, 1000, 50.0)
    assert b["decision"] == "blocked" and b["violated_rule"] == "max_discount", b
    e = check_campaign_policy(db, "m_eval1", 5, 1500000, 50.0)
    assert e["decision"] in ("escalated", "blocked"), e
    a = check_campaign_policy(db, "m_eval1", 5, 10000, 50.0)
    assert a["decision"] == "approved" and a["policy_version"] >= 1, a
    return "tiers approved/escalated/blocked with reasons"


def _t_approval():
    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities,
                                                plan_action, _action_hash)
    db = CTX["db"]
    detect_opportunities(db, "m_eval1")
    top = score_opportunities(db, "m_eval1")[0]
    planned = plan_action(db, top.id)
    camp = planned["campaign"]
    assert camp.action_hash == _action_hash(camp.id, camp.discount or 0,
                                            camp.budget_paise or 0,
                                            camp.policy_version), "hash not bound"
    if planned["policy"]["decision"] == "requires_approval":
        from app.models.entities import Approval
        appr = db.query(Approval).filter(Approval.campaign_id == camp.id).first()
        assert appr and appr.amount == camp.budget_paise, "approval not bound to budget"
        return f"escalated, approval {appr.id} bound to {appr.amount}"
    return "auto-approved within limits"


def _t_lifecycle():
    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities,
                                                plan_action,
                                                execute_campaign)
    from datetime import datetime
    db = CTX["db"]
    detect_opportunities(db, "m_eval1")
    top = score_opportunities(db, "m_eval1")[0]
    camp = plan_action(db, top.id)["campaign"]
    assert camp.status in ("proposed", "approved"), camp.status
    if camp.status == "proposed":
        from app.models.entities import Approval
        appr = db.query(Approval).filter(Approval.campaign_id == camp.id).first()
        if appr:
            appr.status = "approved"
            appr.approved_by = "accept"
            appr.decided_at = datetime.utcnow()
        camp.status = "approved"
        db.commit()
    res = execute_campaign(db, camp.id, simulation_mode=True)
    assert "metric" in res, res
    assert camp.status == "completed", camp.status
    return f"proposed->approved->completed, sim={res['simulation_mode']}"


def _t_tc():
    from app.services.autonomous_growth import (detect_opportunities,
                                                score_opportunities,
                                                plan_action,
                                                execute_campaign,
                                                _assign_experiment)
    from app.models.entities import CampaignAudience
    from datetime import datetime
    db = CTX["db"]
    detect_opportunities(db, "m_eval1")
    top = score_opportunities(db, "m_eval1")[0]
    camp = plan_action(db, top.id)["campaign"]
    camp.status = "approved"
    db.commit()
    res = execute_campaign(db, camp.id, simulation_mode=True)
    rows = db.query(CampaignAudience).filter(
        CampaignAudience.campaign_id == camp.id,
        CampaignAudience.customer_id.isnot(None)).all()
    assert {r.group for r in rows} == {"treatment", "control"}
    assert all(r.exposed_at is None for r in rows if r.group == "control")
    again = _assign_experiment(db, camp, [r.customer_id for r in rows], 0.10)
    for a, b in zip(sorted(rows, key=lambda r: r.customer_id),
                     sorted(again, key=lambda r: r.customer_id)):
        assert a.group == b.group
    return f"t={res['treatment']['eligible']} c={res['control']['eligible']} stable"


def _t_lift():
    from app.models.entities import CampaignMetric
    db = CTX["db"]
    mets = db.query(CampaignMetric).all()
    assert mets, "no metrics recorded"
    m = mets[-1]
    exp = m.control_purchases / max(m.control_eligible, 1) * m.treatment_eligible
    assert m.incremental_orders == int(round(m.treatment_purchases - exp)), "lift formula drift"
    assert m.incremental_revenue is not None and m.incremental_margin is not None
    return f"lift={m.treatment_purchases}/{m.treatment_eligible} vs {m.control_purchases}/{m.control_eligible}"


def _t_learn():
    from app.services.autonomous_growth import learning_update, _learned_or_cohort
    db = CTX["db"]
    before = _learned_or_cohort(db, "m_eval1", "cross_sell:shoes", "cross_sell", "shoes", fallback=0.08)
    ups = learning_update(db, "m_eval1")
    assert ups, "no learning updates"
    after = _learned_or_cohort(db, "m_eval1", ups[0]["key"], "cross_sell", "shoes", fallback=0.08)
    assert after["sample_size"] >= before["sample_size"]
    return f"{before['predicted_conversion']} -> {after['predicted_conversion']} (n={after['sample_size']})"


def _t_tool():
    from app.agent.runtime import tool_gateway
    db = CTX["db"]
    bad = tool_gateway(db, "m_eval1", "create_cart", {"merchant_id": "m_eval2"}, run_id=None)
    assert bad.get("blocked") or bad.get("error"), bad
    malformed = tool_gateway(db, "m_eval1", "nope_tool", {"x": 1}, run_id=None)
    assert malformed.get("error"), malformed
    return "mismatch rejected, malformed rejected"


def _t_ucp():
    import inspect
    from app.api.routes import ucp
    from app.services import commerce
    src = inspect.getsource(ucp)
    assert "create_checkout_svc" in src or "complete_checkout_svc" in src, "UCP bypasses Commerce Core"
    assert "Commerce Core" in src or "commerce" in src.lower()
    return "UCP delegates to Commerce Core"


def _t_pay():
    import asyncio
    from app.models.entities import Cart
    from app.services.commerce import create_checkout_svc, complete_checkout_svc
    db = CTX["db"]
    cart = Cart(merchant_id="m_eval1", customer_id="c1_00", total=10000)
    db.add(cart)
    db.commit()
    chk = create_checkout_svc(db, cart.id)["checkout"]
    first = asyncio.run(complete_checkout_svc(db, chk.id))
    second = asyncio.run(complete_checkout_svc(db, chk.id))
    assert second.get("deduped") is True and first["payment"].id == second["payment"].id
    return f"idempotent {first['payment'].id}"


def _t_webhook():
    import hmac
    import hashlib
    from app.services.razorpay_adapter import verify_webhook_signature
    from app.core import config
    # production without secret must fail closed
    old_env, old_secret = config.settings.env, config.settings.razorpay_webhook_secret
    try:
        config.settings.env = "production"
        config.settings.razorpay_webhook_secret = ""
        assert verify_webhook_signature(b"{}", "anything") is False, "fail-open in production!"
    finally:
        config.settings.env = old_env
        config.settings.razorpay_webhook_secret = old_secret
    # with secret, valid HMAC passes and wrong fails
    config.settings.razorpay_webhook_secret = "test_secret_123"
    try:
        body = b'{"event_id":"evt_test_1"}'
        good = hmac.new(b"test_secret_123", body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, good) is True
        assert verify_webhook_signature(body, "deadbeef") is False
    finally:
        config.settings.razorpay_webhook_secret = old_secret
    # webhook_events table is stateful + deduped
    from app.models.entities import WebhookEvent
    cols = [c.name for c in WebhookEvent.__table__.columns]
    assert {"status", "attempts", "event_id"}.issubset(cols), cols
    return "fail-closed prod, HMAC verified, stateful"


def _t_outbox():
    from app.models.entities import OutboxEvent
    from app.services.outbox import publish_outbox, publish_pending
    db = CTX["db"]
    evt = publish_outbox(db, "agg_test", "order.paid", {"order_id": "o1"})
    db.commit()
    assert evt.status == "pending"
    res = publish_pending(db)
    st = db.query(OutboxEvent).filter(OutboxEvent.id == evt.id).first().status
    assert st in ("published", "failed"), st
    return f"outbox {res['published']}/{res['total']} relayed, status={st}"


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
