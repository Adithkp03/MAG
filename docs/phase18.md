# Phase 18 — Event Architecture
Redis Streams XADD/XREADGROUP/XACK with outbox pattern. publish() does XADD to mag:events:{type} + mag:events:all + writes OutboxEvent pending, fallback to memory streams when REDIS_URL missing. list_events() XREVRANGE, consume() XREADGROUP + XACK per consumer group mag:consumers. create_consumer_group() MKSTREAM idempotent. Health: /api/v1/events/health.

Files: backend/app/core/events.py (XADD/XREADGROUP/XACK/ack), backend/app/models/entities.py:OutboxEvent
