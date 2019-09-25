# import helper first: it monkey-patches I/O if needed
from helper import do_db_tx, do_memcache, do_tx_task, log

import logging
import time

import falcon

app = falcon.API()


def api(route):
    def decorator_api(cls):
        app.add_route(route, cls())
        return cls
    return decorator_api


@api('/_ah/warmup')
class WarmupAPI(object):
    def on_get(self, req, resp):
        pass


@api('/test/log')
class TestLogsAPI(object):
    def on_get(self, req, resp):
        log(logging.CRITICAL, 'hello world')


@api('/test/noop')
class NoOpAPI(object):
    def on_get(self, req, resp):
        pass


@api('/test/sleep')
class SleepAPI(object):
    def on_get(self, req, resp):
        time.sleep(float(req.get_param('s', default=1)))


@api('/test/data')
class GetFakeDataAPI(object):
    def on_get(self, req, resp):
        resp.body = 'x' * int(req.get_param('sz', default=2**20))


@api('/test/memcache')
class MemcacheAPI(object):
    def on_get(self, req, resp):
        do_memcache(int(req.get_param('n', default=10)),
                    int(req.get_param('sz', default=10240)))


@api('/test/dbtx')
class DbTxAPI(object):
    def on_get(self, req, resp):
        do_db_tx(int(req.get_param('n', default=5)))


@api('/test/txtask')
class TxTaskAPI(object):
    def on_get(self, req, resp):
        do_tx_task(int(req.get_param('n', default=5)))
