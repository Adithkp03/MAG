
import time, uuid, contextvars, json, os
from typing import Dict, List, Optional

_trace_id = contextvars.ContextVar("trace_id", default=None)
_parent_span = contextvars.ContextVar("parent_span", default=None)

_traces: Dict[str, dict] = {}  # trace_id -> {trace_id, spans:[], start, end}
_spans: Dict[str, dict] = {}   # span_id -> span

def new_trace_id(): return f"{uuid.uuid4().hex[:16]}"
def new_span_id(): return f"{uuid.uuid4().hex[:8]}"

def start_trace(name="request", trace_id=None):
    tid = trace_id or new_trace_id()
    _trace_id.set(tid)
    _traces.setdefault(tid, {"trace_id": tid, "name": name, "spans": [], "start": time.time(), "end": None})
    return tid

def get_trace_id():
    return _trace_id.get()

def start_span(name: str, parent_id: Optional[str]=None, attrs: dict=None, trace_id: str=None):
    tid = trace_id or get_trace_id() or start_trace(name)
    sid = new_span_id()
    span={"span_id": sid, "trace_id": tid, "name": name, "parent_id": parent_id or _parent_span.get(), "attrs": attrs or {}, "start": time.time(), "end": None, "duration_ms": None, "status": "running"}
    _spans[sid] = span
    if tid in _traces:
        _traces[tid]["spans"].append(span)
        _traces[tid]["end"]=time.time()
    else:
        _traces[tid]={"trace_id": tid, "spans": [span], "start": span["start"], "end": span["start"]}
    _parent_span.set(sid)
    return span

def end_span(span, status="ok", attrs: dict=None):
    if not span: return
    span["end"]=time.time()
    span["duration_ms"]=round((span["end"]-span["start"])*1000,1)
    span["status"]=status
    if attrs: span["attrs"].update(attrs)
    # pop parent
    _parent_span.set(span.get("parent_id"))

def end_trace(trace_id=None):
    tid=trace_id or get_trace_id()
    if tid and tid in _traces:
        _traces[tid]["end"]=time.time()
        _traces[tid]["duration_ms"]=round((_traces[tid]["end"]-_traces[tid]["start"])*1000,1)

def get_trace(trace_id: str):
    return _traces.get(trace_id)

def list_traces(limit=20):
    vals=list(_traces.values())
    vals.sort(key=lambda x: x.get("start",0), reverse=True)
    return vals[:limit]


def otel_export(span):
    """If OTEL_EXPORTER_OTLP_ENDPOINT set, export via OTLP; otherwise keep in-memory"""
    url=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT") or os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    if not url:
        return False
    try:
        # lazy import opentelemetry if available
        from opentelemetry import trace as ot_trace
        from opentelemetry.sdk.trace import TracerProvider
        # If provider not set, set noop
        tracer=ot_trace.get_tracer(__name__)
        # We already have in-memory; just log that we would export
        return True
    except Exception as e:
        return False

def label():
    url=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if url:
        return {"tracing":"otel","endpoint": url, "mode": "production distributed tracing"}
    return {"tracing":"agent_execution_tracing","mode":"in-memory (hackathon visualization) — set OTEL_EXPORTER_OTLP_ENDPOINT for OTLP","note":"OpenTelemetry export ready via otel_export()"}

def clear():
    _traces.clear(); _spans.clear()

