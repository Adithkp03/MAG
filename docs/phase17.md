# Phase 17 — Payment Reliability
Idempotency via X-Idempotency-Key header on POST /api/v1/payments (payments.py). Duplicate key returns existing payment 200 instead of 201. Reconciliation: POST /api/v1/payments/reconcile syncs Razorpay live status to DB (mock or live). Webhook: POST /api/v1/webhooks/razorpay verifies HMAC SHA256 (RAZORPAY_WEBHOOK_SECRET), durable states pending->processed->failed, idempotent by event_id.

Files: backend/app/api/routes/payments.py, backend/app/api/routes/webhooks.py, backend/app/services/razorpay_adapter.py
