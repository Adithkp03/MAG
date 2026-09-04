import time, random, functools, logging
logger = logging.getLogger("mag.retry")

def retry(max_attempts=3, backoff_base=0.5, backoff_factor=2, jitter=True, retry_on=(Exception,)):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            attempt=0
            delay=backoff_base
            while True:
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    attempt+=1
                    if attempt>=max_attempts:
                        logger.warning(f"retry exhausted {fn.__name__} after {attempt}: {e}")
                        raise
                    sleep=delay + (random.uniform(0, delay*0.2) if jitter else 0)
                    logger.info(f"retry {fn.__name__} attempt {attempt}/{max_attempts} sleep {sleep:.2f}s: {e}")
                    time.sleep(sleep)
                    delay*=backoff_factor
        return wrapper
    return deco

async def aretry(max_attempts=3, backoff_base=0.5, backoff_factor=2):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            attempt=0
            delay=backoff_base
            while True:
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    attempt+=1
                    if attempt>=max_attempts: raise
                    import asyncio
                    await asyncio.sleep(delay)
                    delay*=backoff_factor
        return wrapper
    return deco
