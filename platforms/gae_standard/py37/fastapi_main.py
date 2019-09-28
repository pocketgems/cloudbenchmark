# import helper first: it monkey-patches I/O if needed
from helper import APP_ID, dbc, do_db_tx, do_memcache, do_tx_task, log

import functools
import inspect
import logging
import os
import time
import traceback

from fastapi import FastAPI
from starlette.responses import Response


# set default executor to thread pool with # threads = # requests ...  plus
# more if each thread may queue up more than 1 concurrent operation each
if '-ctpe' in os.environ.get('GAE_VERSION', ''):  # only customize sometimes
    import asyncio
    import concurrent.futures
    asyncio.get_event_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=100))





if APP_ID:
    # disable documentation sharing on GAE
    cfg = dict(openapi_url=None, docs_url=None, redoc_url=None)
else:
    # documentation included when running on localhost
    cfg = {}
app = FastAPI(**cfg)


class API:
    """Decorator for creating FastAPI APIs.

    You can wrap a class which contains one or more APIs like:
    @API('/some_route')
    class SomeAPI:
        def get(x: int = 5):
            return dict(x=x)
        def post(y: int):
            return dict(y=y * y)

    This is useful for APIs which benefit from grouping related logic into the
    class. You can also wrap a function for simpler APIs:
    @API.get('/another_route')
    def addTwoNumbers(x: int, y: int):
        return x + y
    """
    METHODS = ('get', 'post')

    def __init__(self, route, method=None):
        self.route = route
        self.method = method

    def __call__(self, cls_or_func):
        if inspect.isclass(cls_or_func):
            return self.wrap_cls(cls_or_func)
        return self.wrap_func(cls_or_func, self.method)

    def wrap_cls(self, another_cls):
        assert not self.method, 'HTTP method is not permitted on classes'
        for method_name in self.METHODS:
            method = getattr(another_cls, method_name, None)
            if method:
                setattr(another_cls, method_name,
                        self.wrap_func(method, method_name))
        return another_cls

    def wrap_func(self, func, method):
        assert method, 'HTTP method must be specified'
        add_route = getattr(app, method, None)
        assert add_route, 'unknown HTTP method ' + method
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ret = func(*args, **kwargs)
            if ret is None:
                return Response(content='')
            return ret
        return add_route(self.route)(wrapper)


def add_api_method(method_name):
    setattr(API, method_name,
            staticmethod(lambda route: API(route, method_name)))


for method_name in API.METHODS:
    add_api_method(method_name)


del add_api_method
del method_name


@API.get('/_ah/warmup')
def WarmupAPI():
    pass


@API.get('/test/log')
def TestLogsAPI():
    log(logging.CRITICAL, 'hello world')


@API.get('/test/noop')
def NoOpAPI():
    pass


@API.get('/test/sleep')
def SleepAPI(s: float = 1):
    """Sleeps for `s` seconds."""
    time.sleep(s)


@API.get('/test/data')
def GetFakeDataAPI(sz: int = 2**20):
    """Returns `sz` bytes of junk data."""
    return Response(content='x' * sz, media_type='text/plain')


@API.get('/test/memcache')
def MemcacheAPI(n: int = 10, sz: int = 10240):
    do_memcache(n, sz)


@API.get('/test/dbtx')
def DbTxAPI(n: int = 5):
    """Does `n` sequential datastore transactions. No contention."""
    do_db_tx(n)


@API.get('/test/txtask')
def TxTaskAPI(n: int = 5):
    """Enqueues a tx task."""
    do_tx_task(n)
