# MAG — What Is Real, What Is Heuristic, What Is Simulated

> Positioning: **data-driven autonomous growth prototype with governed
> execution and measurable outcomes**. Not a trained ML model, not a
> revenue guarantee.

## 1. Genuinely data-driven
- Customer intelligence (RFM, AOV, CLV, category affinity) aggregated from
  the merchant's own `orders -> checkouts -> carts -> cart_items -> products`.
- Product intelligence (velocity units/day, revenue contribution, attach
  rate, conversion, days-of-inventory) from the same history.
  Co-purchase affinity `P(B|A) = pair_count / single_count[A]` is counted,
  not asserted.
- Conversion estimates: `services/conversion.py` — observed cohort
  successes/trials with Bayesian smoothing (prior Beta, weight 20, mean 8%).
  Source is always reported: `historical` (n>=50) / `smoothed` (10<=n<50) /
  `prior` cold-start (n<10) / `learned` (posterior with >=10 observations).
- Margins from `products.cost_price` where present:
  `margin = (price - cost) / price`.
- Treatment/control metrics read per-customer `campaign_audiences` rows
  joined to real `orders`; incremental = treatment actual minus
  control-baseline scaled to treatment population.

## 2. Heuristic (documented formulas, not ML)
- `churn_prob = min(0.95, recency_days/180*0.9 + (0.2 if freq==1 else 0))`
- CLV `= total * (1 + freq*0.25)`; RFM 1-5 thresholds in
  `compute_customer_intelligence`; value segments
  (champion/new/at_risk/churned/high_value/regular) are rule labels.
- Demand trend (`rising` if velocity>1.5, `falling` if <0.3), slow-moving
  score `(doi-30)/90` clamped 0-1.
- Objective ranking: `score = value(objective)*prob - cost - risk_penalty`,
  value axis = margin objective -> incremental margin; revenue ->
  0.35*rev + 0.65*margin; clearance boosts dead_stock 1.2x; retention boosts
  churn/repeat 1.25x. Risk tolerance scales the penalty (low 2x, high 0.5x).

## 3. Learned (persisted, reused)
- `learning_state` per (merchant, key): Beta-Binomial posterior
  `alpha = 2 + successes`, `beta = 2 + failures`, 95% CI, source
  `observed` or `simulated`. The next `detect` run prefers posteriors with
  >=10 observations over cohort estimates (`_learned_or_cohort`), so
  measured outcomes change future rankings. Dashboard shows
  previous -> observed -> updated + sample + CI.

## 4. Simulated (demo mode, explicitly flagged)
- `execute_campaign(..., simulation_mode=True)` (default): per-customer
  responses drawn from a seeded RNG are written with `is_simulated=True`,
  metric carries `simulation_mode=True`, and API/dashboard label it
  **"Demo simulation — not observed customer behavior"**.
- Production (`simulation_mode=False`): only assignment + exposure happen
  in execute; purchases arrive via `record_observed_purchase()` from real
  order events. No external ESP/SMS/ad delivery exists — exposure is the
  in-product event layer (see `docs/events.md`); wire a real channel before
  claiming real-world lift.

## 5. Requires external integration for production
- Razorpay live keys + webhook secret + public webhook URL (ngrok in dev).
  Without keys the adapter returns mock orders and reconciliation degrades.
- Redis for Streams/caching (in-memory fallback is dev-only, single-replica).
- PostgreSQL/Supabase: production fails fast without it (no sqlite fallback).
- Real delivery channel (email/SMS/ads) for treatment exposure.

## 6. Merchant policy
Tiers `approved | escalated | blocked` (`app/trust/policy.py`):
auto-approve within `auto_approve_limit`; escalate to 2x / `hard_block_limit`;
discount over max -> block; margin below min -> block; budget over max ->
escalate (<=2x) else block; low risk tolerance escalates high spend/discount.
`check_campaign_policy` enforces max discount, budget, min margin server-side.

## 7. Approval
Bound to merchant + campaign + budget amount + policy version + action hash
(`_action_hash`), 7-day expiry. Execution re-verifies all five; mutation or
stale policy invalidates (`expired`, re-plan required). `X-Approved-By` is an
identity claim recorded on the DB approval — never trusted alone.

## 8. Treatment/control
Stable hash assignment `sha256(campaign:customer) % 100`, default 10%
control (configurable `experiment_ratio`, capped 50%). Control never gets
exposure or treatment orders. Metrics per arm + incremental vs scaled
control baseline + CI; `sample_adequate` requires >=30 treatment and >=10
control eligible — smaller samples must not claim significance.

## 9. Bayesian updating
Prior Beta(2,2); posterior accumulates every measured campaign's treatment
trials/successes per learning key; cold-start falls back to cohort, then to
an explicitly labeled prior. Simulated runs update with source=`simulated`
so demo data never silently pollutes production priors.

## 10. UCP mapping
UCP adapter (`api/routes/ucp.py`) is a storefront façade: discover ->
catalog -> checkout CRUD -> complete/cancel, all delegating to
`services/commerce.py` + `services/catalog.py` (canonical Commerce Core).
No duplicate checkout logic. No claim of official UCP spec conformance.

## 11. Payment/webhook reconciliation
Razorpay order -> `pay_<checkout_id>` idempotent payment -> webhook HMAC ->
state machine received/processing/processed/failed with retry on stored
event -> captured/failed -> order paid/failed -> outbox events
(`payment.captured`, `order.paid`). Provider confirmation is authoritative;
webhook secret missing in production fails closed (401, integration
reported unhealthy). No secrets in logs.
