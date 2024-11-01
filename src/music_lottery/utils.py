import functools
from typing import Union
import asyncio
import threading
from typing import Callable
from contextlib import asynccontextmanager


def with_lock(lock: threading.Lock):
    def deco(func: Callable):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            with lock:
                return func(*args, **kwargs)

        return wrapped

    return deco


async def run_as_async[
    T
](
    func: Callable[..., T],
    args=(),
    kwargs=None,
    daemon: bool = True,
    check_delay: Union[float, int] = 0.1,
) -> T:
    thread = threading.Thread(
        target=func,
        args=args,
        kwargs=kwargs,
        name=getattr(func, "__name__", str(func)),
        daemon=daemon,
    )
    thread.start()
    while thread.is_alive():
        await asyncio.sleep(check_delay)
