import asyncio
from typing import AsyncGenerator
from contextlib import asynccontextmanager


class RWContext:
    """
    from melobot.utils
    """

    def __init__(self, read_limit: int | None = None) -> None:
        """初始化异步读写上下文

        :param read_limit: 读取的数量限制，为空则不限制
        """
        self.write_semaphore = asyncio.Semaphore(1)
        self.read_semaphore = asyncio.Semaphore(read_limit) if read_limit else None
        self.read_num = 0
        self.read_num_lock = asyncio.Lock()

    @asynccontextmanager
    async def read(self) -> AsyncGenerator[None, None]:
        """上下文管理器，展开一个关于该对象的安全异步读上下文"""
        if self.read_semaphore:
            await self.read_semaphore.acquire()

        async with self.read_num_lock:
            if self.read_num == 0:
                await self.write_semaphore.acquire()
            self.read_num += 1

        try:
            yield
        finally:
            async with self.read_num_lock:
                self.read_num -= 1
                if self.read_num == 0:
                    self.write_semaphore.release()
                if self.read_semaphore:
                    self.read_semaphore.release()

    @asynccontextmanager
    async def write(self) -> AsyncGenerator[None, None]:
        """上下文管理器，展开一个关于该对象的安全异步写上下文"""
        await self.write_semaphore.acquire()
        try:
            yield
        finally:
            self.write_semaphore.release()
