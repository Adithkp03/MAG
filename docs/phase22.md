# Phase 22 — Deployment
Dockerfile: python:3.11-slim backend + node:20-alpine frontend multi-stage. docker-compose.prod.yml: backend + redis with healthcheck curl /health/ready, ENV production, Supabase Postgres hosted (not in compose). CI: .github/workflows/ci.yml with redis service, deterministic seed hash check, pytest backend/tests/test_evaluation.py, alembic check. Env: backend/.env.example (DATABASE_URL REDIS_URL GROQ RAZORPAY JWT ALLOWED_ORIGINS etc).

Files: Dockerfile, docker-compose.prod.yml, .github/workflows/ci.yml, backend/.env.example
