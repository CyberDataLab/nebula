import asyncio
import inspect
import logging
import threading


class Locker:
    def __init__(self, name, verbose=True, async_lock=False, *args, **kwargs):
        self._name = name
        self._verbose = verbose
        self._async_lock = async_lock

        if async_lock:
            self._lock = asyncio.Lock(*args, **kwargs)
        else:
            self._lock = threading.Lock(*args, **kwargs)

    def acquire(self, *args, **kwargs):
        caller = inspect.stack()[1]
        filename = caller.filename.split("/")[-1]
        lineno = caller.lineno
        if self._verbose:
            if "timeout" in kwargs:
                logging.debug(
                    f"🔒  Acquiring lock [{self._name}] from {filename}:{lineno} with timeout {kwargs['timeout']}"
                )
            else:
                logging.debug(f"🔒  Acquiring lock [{self._name}] from {filename}:{lineno}")
        if self._async_lock:
            raise RuntimeError("Use 'await acquire_async' for acquiring async locks")
        return self._lock.acquire(*args, **kwargs)

    def release(self, *args, **kwargs):
        caller = inspect.stack()[1]
        filename = caller.filename.split("/")[-1]
        lineno = caller.lineno
        if self._verbose:
            logging.debug(f"🔓  Releasing lock [{self._name}] from {filename}:{lineno}")
        self._lock.release()

    def locked(self):
        result = self._lock.locked()
        if self._verbose:
            logging.debug(f"🔐  Lock [{self._name}] is locked? {result}")
        return result

    def __enter__(self):
        if self._async_lock:
            raise RuntimeError("Use 'async with' for acquiring async locks")
        logging.debug(f"🔒  Acquiring lock [{self._name}] using [with] statement")
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._async_lock:
            raise RuntimeError("Use 'async with' for releasing async locks")
        logging.debug(f"🔓  Releasing lock [{self._name}] using [with] statement")
        self.release()

    async def acquire_async(self, *args, **kwargs):
        caller = inspect.stack()[1]
        filename = caller.filename.split("/")[-1]
        lineno = caller.lineno
        if not self._async_lock:
            raise RuntimeError("Use 'acquire' for acquiring non-async locks")
        if self._verbose:
            logging.debug(f"🔒  Acquiring async lock [{self._name}] from {filename}:{lineno}")
        await self._lock.acquire()

    async def release_async(self, *args, **kwargs):
        caller = inspect.stack()[1]
        filename = caller.filename.split("/")[-1]
        lineno = caller.lineno
        if not self._async_lock:
            raise RuntimeError("Use 'release' for releasing non-async locks")
        if self._verbose:
            logging.debug(f"🔓  Releasing async lock [{self._name}] from {filename}:{lineno}")
        self._lock.release()

    async def locked_async(self):
        result = self._lock.locked()
        if self._verbose:
            logging.debug(f"🔐  Async lock [{self._name}] is locked? {result}")

    async def __aenter__(self):
        logging.debug(f"🔒  Acquiring async lock [{self._name}] using [async with] statement")
        await self.acquire_async()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        logging.debug(f"🔓  Releasing async lock [{self._name}] using [async with] statement")
        await self.release_async()
