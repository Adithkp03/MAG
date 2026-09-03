
import json, time, uuid
_events = []  # in-memory for dev, replace with Redis Streams
def publish(event_type: str, payload: dict):
    evt = {"event_id": f"evt_{uuid.uuid4().hex[:8]}", "type": event_type, "payload": payload, "ts": time.time()}
    _events.append(evt)
    return evt
def list_events(limit=50):
    return _events[-limit:]
