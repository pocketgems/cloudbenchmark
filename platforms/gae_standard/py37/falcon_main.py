# import helper first: it monkey-patches I/O if needed
from helper import APP_ID, do_db_json, do_memcache, log

import logging
import os
import time

import falcon

if 'ndb' in os.environ.get('GAE_VERSION', ''):
    from helper_ndb import do_db_indir_sync, do_db_indirb, do_db_tx, do_tx_task
else:
    from helper_db import do_db_indir_sync, do_db_indirb, do_db_tx, do_tx_task


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


@api('/test/dbjson')
class DbJsonAPI(object):
    def on_get(self, req, resp):
        do_db_json()


@api('/test/dbindir')
class DbIndirAPI(object):
    def on_get(self, req, resp):
        resp.body = do_db_indir_sync(int(req.get_param('n', default=3)))


@api('/test/dbindirb')
class DbIndirbAPI(object):
    def on_get(self, req, resp):
        resp.body = do_db_indirb(int(req.get_param('n', default=3)))
