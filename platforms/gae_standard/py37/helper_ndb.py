from helper import APP_ID, taskq

import base64
import random
import uuid

from aioify import aioify
from google.cloud import ndb

ndbc = ndb.Client()


def do_db_tx(n):
    with ndbc.context():
        random_id = uuid.uuid4().hex
        for ignore in range(n):
            ndb.transaction(lambda: incr_db_entry(random_id).put(),
                            xg=False)


def do_tx_task(n):
    for ignore in range(n):
        tx_id = uuid.uuid4().hex
        fq_queue_name = taskq.queue_path(
            APP_ID or 'benchmarkgcp2',
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
            with ndbc.context():
                tx_helper(random_id, tx_id)
        except:
            taskq.delete_task(new_task.name)
            raise


@ndb.transactional(xg=True)
def tx_helper(random_id, tx_id):
    counter = incr_db_entry(random_id)
    tx_done_sentinel = TxDoneSentinel(id=tx_id)
    ndb.put_multi([counter, tx_done_sentinel])


class Counter(ndb.Model):
    _use_cache = _use_memcache = False
    count = ndb.IntegerProperty(default=0, indexed=False)


class TxDoneSentinel(ndb.Model):
    _use_cache = _use_memcache = False


def incr_db_entry(some_id):
    """tries to get a db entity which won't exist and then creates it"""
    x = Counter.get_by_id(some_id)
    if not x:
        x = Counter(id=some_id)
    x.count += 1
    return x


class OneInt(ndb.Model):
    _use_cache = _use_memcache = False


async def do_db_indir_async(n):
    return await aioify_do_db_indir(n)


def do_db_indir_sync(n):
    with ndbc.context():
        futures = [_get_and_get_dependency() for ignore in range(n)]
        return str(sum(f.get_result() for f in futures))


aioify_do_db_indir = aioify(do_db_indir_sync)


@ndb.tasklet
def _get_and_get_dependency():
    x = yield _get_random_key().get_async()
    if not x:
        raise Exception('OneInt entity missing (not yet defined?)')
    new_idx = (2 * x.key.id()) % 10000
    subx = yield ndb.Key(OneInt, new_idx).get_async()
    raise ndb.Return(subx.key.id() + x.key.id())


def _get_random_key():
    return ndb.Key(OneInt, random.randint(0, 9999))


def do_db_indirb(n):
    with ndbc.context():
        keys = [_get_random_key() for ignore in range(n)]
        entities = ndb.get_multi(keys)
        if None in entities:
            raise Exception('OneInt entity missing (not yet defined?)')
        new_keys = [ndb.Key(OneInt, (2 * x.key.id()) % 10000)
                    for x in entities]
        entities.extend(ndb.get_multi(new_keys))
        return str(sum(x.key.id() for x in entities))
