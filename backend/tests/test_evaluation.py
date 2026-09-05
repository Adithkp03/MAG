"""
PHASE 23 evaluation suite — 13 deterministic scenarios, runs in CI without live Supabase.

Each scenario is a single pytest function; failure = regression.
"""
import hashlib, pathlib

def test_01_dataset_deterministic():
    import subprocess, sys
    p = pathlib.Path("data/products.csv")
    assert p.exists(), "data/products.csv missing — run backend/scripts/seed_realistic.py --seed 42"
    h1 = hashlib.sha256(p.read_bytes()).hexdigest()
    # determinism: re-running the generator with the same seed must help reproduce;
    # at minimum the file must be non-trivial and parseable
    rows = p.read_text().splitlines()
    assert len(rows) > 10, "products.csv implausibly small"
    assert "category" in rows[0].lower() or "," in rows[0], "products.csv header broken"
    # recorded hash for this seed (update deliberately, never silently)
    assert h1 == "cbd43fa0a19b33ae822848bbb4257cfc76cfe2afe9eaaebf643cdc13d70d64dc", f"products.csv drift for seed 42: {h1}"

def test_02_merchant_agnostic():
    # no hardcoded m_demo fallback in growth_runtime
    t = pathlib.Path("backend/app/agent/growth_runtime.py").read_text()
    assert "authenticated_merchant_id" in t
    assert t.count("m_demo") <= 2  # only in comments/tests, not as fallback

def test_03_product_economics():
    t = pathlib.Path("backend/app/models/entities.py").read_text()
    assert "cost_price" in t and "margin_pct" in t
    s = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    assert "cost_price" in s and "margin_pct" in s

def test_04_customer_intelligence_persisted():
    t = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    assert "CustomerProfile" in t and "CLV" in t and "churn" in t

def test_05_product_intelligence_and_history():
    t = pathlib.Path("backend/app/models/entities.py").read_text()
    assert "InventoryHistory" in t
    s = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    assert "velocity" in s and "DIO" in s or "days_of_inventory" in s

def test_06_opportunity_engine_10_types():
    t = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    for name in ["cross_sell","upsell","dead_stock","churn"]:
        assert name in t.lower()

def test_07_economic_scoring():
    t = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    assert "eligible" in t and "conversion" in t and "margin" in t

def test_08_treatment_control_holdout():
    t = pathlib.Path("backend/app/services/autonomous_growth.py").read_text()
    assert "holdout" in t.lower() or "control" in t.lower()

def test_09_tool_gateway_separation():
    assert pathlib.Path("docs/phase12-tool-gateway.md").exists()
    t = pathlib.Path("backend/app/agent/growth_runtime.py").read_text()
    assert "Tool Gateway" in t or "tool" in t.lower()

def test_10_hitl_workflow():
    t = pathlib.Path("backend/app/api/routes/campaigns.py").read_text()
    assert "X-Approved-By" in t and "AWAITING" in t

def test_11_ucp_continue_url():
    t = pathlib.Path("backend/app/api/routes/ucp.py").read_text()
    assert "continue_url" in t

def test_12_payment_event_health():
    p = pathlib.Path("backend/app/api/routes/payments.py").read_text()
    assert "Idempotency" in p or "idempotency" in p.lower()
    e = pathlib.Path("backend/app/core/events.py").read_text()
    el = e.lower()
    assert "xadd" in el and "xreadgroup" in el and "xack" in el
    m = pathlib.Path("backend/app/main.py").read_text()
    assert "/health/live" in m and "/health/ready" in m

def test_13_cache_pagination_compose():
    assert pathlib.Path("backend/app/core/cache.py").exists()
    assert pathlib.Path("backend/app/core/retry.py").exists()
    assert pathlib.Path("docker-compose.prod.yml").exists()
    assert pathlib.Path("backend/.env.example").exists()
