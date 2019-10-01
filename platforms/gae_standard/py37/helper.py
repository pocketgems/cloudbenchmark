from aioify import aioify
import asyncio
import os
import random
import zlib

import ujson


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



log(logging.CRITICAL, 'ver=%s' % os.environ.get('GAE_VERSION', ''))

import threading
log(logging.CRITICAL, 'stack_size=%s  os_default=%s' % (
    threading.stack_size(), os.environ.get('TSSULIMIT')))

# TODO: set default stack size for threads ... small-ish?

import base64
import uuid

from google.cloud import datastore as db, tasks_v2
import redis

dbc = db.Client()
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


def do_db_tx(n):
    random_id = uuid.uuid4().hex
    for ignore in range(n):
        with dbc.transaction():
            dbc.put(incr_db_entry(random_id))


def do_tx_task(n):
    for ignore in range(n):
        tx_id = uuid.uuid4().hex
        fq_queue_name = taskq.queue_path(
            APP_ID,
            'us-central1',
            'testpy3')  # this is the queue name
        task = dict(
            app_engine_http_request=dict(
                http_method='POST',
                relative_uri='/handleTxTask',
                body=base64.b64encode(b'x' * 512),  # encode to bytes
                app_engine_routing=dict(
                    service='py3',
                    version='txtaskhandler',
                ),
                headers=dict(
                    TXID=tx_id,
                ),
            ),
        )
        # TODO: create_task is a synchronous API call; better to NOT block on
        #       it until we need to commit our tx ... and not a moment before!
        new_task = taskq.create_task(fq_queue_name, task)
        random_id = uuid.uuid4().hex
        try:
            with dbc.transaction():
                counter = incr_db_entry(random_id)
                tx_done_sentinel = db.Entity(key=dbc.key('TxDoneSentinel',
                                                         tx_id))
                dbc.put_multi([counter, tx_done_sentinel])
        except:
            taskq.delete_task(new_task['name'])


def incr_db_entry(some_id):
    """tries to get a db entity which won't exist and then creates it"""
    key = dbc.key('Counter', some_id)
    x = dbc.get(key)
    if not x:
        x = db.Entity(key=key,
                      exclude_from_indexes=('count',))
        x['count'] = 0
    x['count'] += 1
    return x


LARGE_JSON = None


def do_db_json():
    global LARGE_JSON
    if not LARGE_JSON:
        with open('big.json', 'rb') as fin:
            LARGE_JSON = ujson.loads(fin.read())
        raise Exception('read from file')  # don't include in benchmark
    random_id = uuid.uuid4().hex
    key = dbc.key('BigJsonHolder', random_id)
    x = db.Entity(key=key, exclude_from_indexes=('data',))
    x['data'] = zlib.compress(ujson.dumps(LARGE_JSON).encode('utf-8'))
    dbc.put(x)
    x = dbc.get(key)
    data = zlib.decompress(x['data'])
    ujson.loads(data)
    return len(data)


def _get_key(i=None):
    return dbc.key('OneInt', random.randint(0, 9999) if i is None else i)


async def do_db_indir_async(n):
    futures = {_get_and_then_get_dependency() for i in range(n)}
    done = (await asyncio.wait(futures))[0]
    return str(sum(x.result() for x in done))


def do_db_indir_sync(n):
    return asyncio.run(do_db_indir_async(n))


async_dbc_get = aioify(dbc.get)


async def _get_and_then_get_dependency():
    x = await async_dbc_get(_get_key())
    if x is None:  # bool(x) is False because x has no props ... gross
        raise Exception('OneInt entity missing (not yet defined?)')
    new_idx = (2 * x.id) % 10000
    subx = await async_dbc_get(dbc.key('OneInt', new_idx))
    return subx.id + x.id


def do_db_indirb(n):
    keys = [_get_key() for i in range(n)]
    entities = dbc.get_multi(keys)
    if None in entities:
        raise Exception('OneInt entity missing (not yet defined?)')
    new_keys = [_get_key((2 * x.id) % 10000) for x in entities]
    entities.extend(dbc.get_multi(keys))
    return str(sum(x.id for x in entities))
