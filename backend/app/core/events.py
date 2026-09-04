
import json, time, uuid, os
from typing import Dict, Any

_redis = None
_stream_prefix = "mag:events"

def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL") or os.getenv("UPSTASH_REDIS_URL") or ""
    if not url:
        # try config
        try:
            from .config import settings
            url = getattr(settings, "redis_url", "") or ""
        except: pass
    if not url or "xxx" in url.lower():
        return None
    try:
        import redis
        _redis = redis.from_url(url, decode_responses=True, socket_connect_timeout=3, socket_timeout=3)
        _redis.ping()
        return _redis
    except Exception as e:
        print(f"redis unavailable, fallback to memory: {e}")
        return None

# fallback memory store with stream-like structure
_memory_streams: Dict[str, list] = {}
_memory_events = []

def publish(event_type: str, payload: dict):
    evt = {"event_id": f"evt_{uuid.uuid4().hex[:8]}", "type": event_type, "payload": payload, "ts": time.time(), "stream": f"{_stream_prefix}:{event_type}"}
    # Phase 18: outbox pattern — also persist to outbox_events for durable delivery
    try:
        from .database import SessionLocal
        from ..models.entities import OutboxEvent
        db=SessionLocal()
        try:
            db.add(OutboxEvent(aggregate_id=payload.get("payment_id") or payload.get("order_id") or payload.get("campaign_id") or payload.get("checkout_id") or evt["event_id"], event_type=event_type, payload={"event_id": evt["event_id"], "type": event_type, **payload}, status="pending"))
            db.commit()
        except Exception as e:
            db.rollback()
        finally:
            db.close()
    except Exception as e:
        pass
    r = _get_redis()
    if r:
        try:
            stream = f"{_stream_prefix}:{event_type}"
            r.xadd(stream, {"event_id": evt["event_id"], "type": event_type, "payload": json.dumps(payload), "ts": str(evt["ts"])}, maxlen=5000, approximate=True)
            # also global stream
            r.xadd(f"{_stream_prefix}:all", {"event_id": evt["event_id"], "type": event_type, "payload": json.dumps(payload)}, maxlen=10000, approximate=True)
            return evt
        except Exception as e:
            print(f"redis xadd failed {e}, fallback memory")
    # memory fallback
    _memory_events.append(evt)
    # per-type stream
    _memory_streams.setdefault(event_type, []).append(evt)
    _memory_streams.setdefault("all", []).append(evt)
    # keep cap
    if len(_memory_events) > 5000:
        _memory_events.pop(0)
    return evt

def list_events(limit=50):
    r = _get_redis()
    if r:
        try:
            # read from global stream
            rows = r.xrevrange(f"{_stream_prefix}:all", count=limit)
            out=[]
            for _, fields in rows:
                try: payload=json.loads(fields.get("payload","{}"))
                except: payload=fields.get("payload")
                out.append({"event_id": fields.get("event_id"), "type": fields.get("type"), "payload": payload, "ts": float(fields.get("ts",0))})
            return list(reversed(out))
        except Exception as e:
            print(f"redis xrevrange failed {e}")
    return _memory_events[-limit:]

def list_stream(event_type: str, limit=20):
    r=_get_redis()
    if r:
        try:
            rows=r.xrevrange(f"{_stream_prefix}:{event_type}", count=limit)
            out=[]
            for _, fields in rows:
                out.append({"event_id": fields.get("event_id"), "type": fields.get("type"), "payload": json.loads(fields.get("payload","{}"))})
            return list(reversed(out))
        except: pass
    return _memory_streams.get(event_type, [])[-limit:]

def health():
    r=_get_redis()
    if r:
        try: r.ping(); return {"backend":"redis","ok": True}
        except Exception as e: return {"backend":"redis","ok": False, "error": str(e)}
    return {"backend":"memory","ok": True, "note": "set REDIS_URL for Redis Streams"}


def create_consumer_group(stream: str, group: str):
    """Idempotent consumer group creation (XGROUP CREATE MKSTREAM)"""
    r=_get_redis()
    if not r: return {"backend":"memory","note":"no redis - consumers run in-process on memory streams"}
    try:
        # MKSTREAM creates stream if not exists
        r.xgroup_create(stream, group, id="0", mkstream=True)
        return {"ok": True, "stream": stream, "group": group}
    except Exception as e:
        if "BUSYGROUP" in str(e):
            return {"ok": True, "stream": stream, "group": group, "existing": True}
        return {"ok": False, "error": str(e)}

def consume(group: str, consumer: str, streams: dict, count: int=10, block_ms: int=500):
    """XREADGROUP for consumer group; falls back to memory streams"""
    r=_get_redis()
    if r:
        try:
            # ensure groups
            for s in streams:
                create_consumer_group(s, group)
            resp=r.xreadgroup(group, consumer, streams, count=count, block=block_ms)
            out=[]
            for stream_name, entries in (resp or []):
                for eid, fields in entries:
                    try: payload=json.loads(fields.get("payload","{}"))
                    except: payload=fields.get("payload")
                    out.append({"stream": stream_name, "id": eid, "event_id": fields.get("event_id"), "type": fields.get("type"), "payload": payload})
                    # ack
                    try: r.xack(stream_name, group, eid)
                    except: pass
            return out
        except Exception as e:
            print(f"consume failed {e}")
    # memory fallback: drain from _memory_streams
    out=[]
    for s, cnt in streams.items():
        # s is like mag:events:cart.created -> type is after last :
        typ=s.split(":")[-1] if ":" in s else s
        buf=_memory_streams.get(typ, [])
        # also check "all" as aggregation
        take=min(cnt if isinstance(cnt, int) else 10, len(buf))
        for _ in range(take):
            if buf:
                evt=buf.pop(0)
                out.append({"stream": s, "id": evt["event_id"], "event_id": evt["event_id"], "type": evt["type"], "payload": evt["payload"]})
    return out

def ack(stream: str, group: str, eid: str):
    r=_get_redis()
    if r:
        try: r.xack(stream, group, eid)
        except: pass

# Event names per spec
EVENTS = [
    "cart.created","cart.updated",
    "checkout.created","checkout.updated",
    "authorization.requested","authorization.approved",
    "payment.created","payment.captured","payment.failed",
    "order.paid","order.created",
    "campaign.created","campaign.approved","campaign.executed",
    "recommendation.accepted","agent.action"
]
