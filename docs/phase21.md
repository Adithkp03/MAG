# Phase 21 — Production Infra
Structured JSON logging: JsonFormatter with trace_id for production (main.py), log_level from config. Health: /health/ready (db ping + redis ping), /health/live (liveness). Retry/backoff: backend/app/core/retry.py exponential 0.5s*2 jitter 3 attempts sync+async for external calls (Razorpay/Groq).

Files: backend/app/main.py:JsonFormatter+health, backend/app/core/retry.py
