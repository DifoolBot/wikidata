import time
from functools import wraps

def rate_limit(seconds):
    def decorator(func):
        last_called = [0]

        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            wait_time = max(0, seconds - elapsed)
            if wait_time > 0:
                print(f"Rate limited. Waiting for {wait_time:.2f} seconds.")
                time.sleep(wait_time)
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            return result

        return wrapper

    return decorator
