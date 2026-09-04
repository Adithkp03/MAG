# Phase 23 — Evaluation Suite
13 deterministic pytest scenarios in backend/tests/test_evaluation.py: dataset hash, merchant-agnostic, cost_price/margin, customer RFM/CLV/churn, product velocity/DIO, 10 opportunity types, economic scoring, holdout incrementality, tool gateway, HITL X-Approved-By, UCP continue_url, payment idempotency + Streams + health, cache/retry/compose. Runs in CI (python -m pytest) in ~0.03s, no DB required. Hash pins: data/products.csv sha256 81445a...

Files: backend/tests/test_evaluation.py, .github/workflows/ci.yml
