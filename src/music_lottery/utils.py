import functools
import threading
from typing import Callable


def with_lock(lock: threading.Lock):
    def deco(func: Callable):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)

        return wrapped

    return deco
