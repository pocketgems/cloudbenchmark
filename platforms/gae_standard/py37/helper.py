from aioify import aioify
import asyncio
import os
import random
import zlib


APP_ID = os.environ.get('GAE_APPLICATION', '').replace('s~', '')
# if running uwsgi+gevent (ONLY) then we need to monkeypatch because it doesn't
# monkey-patch for us
if 'gevent' in os.environ.get('GAE_VERSION', ''):
    import gevent.monkey
    gevent.monkey.patch_all()
    # datastore API will hang without this
    import grpc.experimental.gevent as grpc_gevent
    grpc_gevent.init_gevent()
elif 'meinheld' in os.environ.get('GAE_VERSION', ''):
    from meinheld import patch
    patch.patch_all()


# ensure the connection pool is big enough for each worker (max workers is 80,
# since each instance can only handle at most 80 concurrent connections)
MAX_CONCURRENT_REQUESTS = 80
from urllib3 import connectionpool, poolmanager
class MyHTTPConnectionPool(connectionpool.HTTPConnectionPool):
    def __init__(self, *args, **kwargs):
        kwargs['maxsize'] = MAX_CONCURRENT_REQUESTS
        super(MyHTTPConnectionPool, self).__init__(*args, **kwargs)
poolmanager.pool_classes_by_scheme['http'] = MyHTTPConnectionPool
class MyHTTPSConnectionPool(connectionpool.HTTPSConnectionPool):
    def __init__(self, *args, **kwargs):
        kwargs['maxsize'] = MAX_CONCURRENT_REQUESTS
        super(MyHTTPSConnectionPool, self).__init__(*args, **kwargs)
poolmanager.pool_classes_by_scheme['https'] = MyHTTPSConnectionPool


import logging
if APP_ID:  # running in the dev server
    import google.cloud.logging
    from google.cloud.logging.resource import Resource
    log_client = google.cloud.logging.Client()
    log_name = 'appengine.googleapis.com%2Fstdout'
    res = Resource(type='gae_app',
                   labels=dict(
                       project_id=APP_ID,
                       module_id=os.environ.get('GAE_SERVICE', '')))
    logger = log_client.logger(log_name)
    def log(severity, msg, *args):
        msg = msg % args
        if severity == logging.DEBUG:
            severity = 'DEBUG'
        elif severity == logging.INFO:
            severity = 'INFO'
        elif severity == logging.WARN:
            severity = 'WARN'
        elif severity == logging.ERROR:
            severity = 'ERROR'
        elif severity == logging.CRITICAL:
            severity = 'CRITICAL'
        else:
            raise RuntimeError('unknown severity for log: %s' % msg)
        logger.log_struct({'message': msg}, resource=res, severity=severity)
else:
    def log(severity, msg, *args):
        logging.log(severity, msg, *args)


import base64
import uuid

from google.cloud import tasks_v2
import redis

if 'REDIS_HOST' in os.environ:
    rcache = redis.Redis(host=os.environ['REDIS_HOST'],
                         port=int(os.environ['REDIS_PORT']))
else:
    log(logging.WARN, 'missing redis creds')
    rcache = None
taskq = tasks_v2.CloudTasksClient.from_service_account_json(
    'cloudtasksaccount.json')


def do_memcache(n, sz):
    key = uuid.uuid4().hex
    val = b'x' * sz
    rcache.set(key, val, ex=60)
    for ignore in range(n):
        assert rcache.get(key) == val


def do_db_json(json_only=False):
    import helper_db
    return helper_db.do_db_json(json_only)
