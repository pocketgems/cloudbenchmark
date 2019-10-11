from helper import APP_ID, log, taskq

from aioify import aioify
import asyncio
import base64
import json
import logging
import os
import random
import uuid
import zlib

from google.cloud import datastore as db
try:
    import orjson as json
    IS_ORJSON = True
except ModuleNotFoundError:
    import json
    log(logging.INFO, 'using std lib json (not orjson)')
    IS_ORJSON = False


dbc = db.Client()


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
            raise


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


def do_db_json(json_only=False):
    global LARGE_JSON
    if not LARGE_JSON:
        with open('big.json', 'rb') as fin:
            LARGE_JSON = json.loads(fin.read())
        raise Exception('read from file')  # don't include in benchmark
    dump = json.dumps(LARGE_JSON)
    if not IS_ORJSON:
        dump = dump.encode('utf-8')
    if json_only:
        json.loads(dump)
        return 'did json only'
    random_id = uuid.uuid4().hex
    key = dbc.key('BigJsonHolder', random_id)
    x = db.Entity(key=key, exclude_from_indexes=('data',))
    x['data'] = zlib.compress(dump)
    dbc.put(x)
    x = dbc.get(key)
    data = zlib.decompress(x['data'])
    json.loads(data)
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
