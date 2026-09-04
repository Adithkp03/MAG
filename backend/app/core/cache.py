import time, json, logging
from functools import wraps
from ..core.config import settings

logger = logging.getLogger("mag.cache")

_cache = {}
# simple in-process cache fallback when Redis unavailable
def _mem_get(key): 
    v = _cache.get(key)
    if not v: return None
    if v["exp"] < time.time():
        _cache.pop(key, None)
        return None
    return v["val"]
def _mem_set(key, val, ttl):
    _cache[key] = {"val": val, "exp": time.time()+ttl}

def _redis():
    try:
        import redis
        r = redis.from_url(settings.redis_url, socket_connect_timeout=1, socket_timeout=1, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None

def cache_get(key: str):
    r = _redis()
    if r:
        try:
            v = r.get(f"mag:{key}")
            if v: return json.loads(v)
        except Exception as e:
            logger.debug(f"redis get failed {e}")
    return _mem_get(f"mag:{key}")

def cache_set(key: str, val, ttl: int = None):
    ttl = ttl or settings.cache_ttl_seconds
    r = _redis()
    if r:
        try:
            r.setex(f"mag:{key}", ttl, json.dumps(val, default=str))
            return
        except Exception as e:
            logger.debug(f"redis set failed {e}")
    _mem_set(f"mag:{key}", val, ttl)

def cached(ttl: int = None, key_prefix: str = ""):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # build key from fn name + args/kwargs (merchant_id etc.)
            parts = [key_prefix or fn.__name__]
            for k in sorted(kwargs.keys()):
                parts.append(f"{k}={kwargs[k]}")
            # also hash first arg if string
            if args and isinstance(args[0], str):
                parts.append(f"arg0={args[0]}")
            key = ":".join(parts)[:200]
            hit = cache_get(key)
            if hit is not None:
                return hit
            res = fn(*args, **kwargs)
            try:
                cache_set(key, res, ttl)
            except Exception:
                pass
            return res
        return wrapper
    return deco

def invalidate(prefix: str):
    # naive invalidate: clear mem keys with prefix, redis scan
    for k in list(_cache.keys()):
        if prefix in k:
            _cache.pop(k, None)
    r = _redis()
    if r:
        try:
            for k in r.scan_iter(match=f"mag:*{prefix}*"):
                r.delete(k)
        except Exception:
            pass
