import logging
import os

APP_ID = os.environ.get('GAE_APPLICATION', '').replace('s~', '')


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


# if running uwsgi+gevent (ONLY) then we need to monkeypatch because it doesn't
# monkey-patch for us
if 'uwsgi-gevent' in os.environ.get('GAE_SERVICE', ''):
    import gevent.monkey
    gevent.monkey.patch_all()
    log(logging.WARN, 'monkey-patching for gevent')


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
    for ignore in range(n):
        random_id = uuid.uuid4().hex
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
                body=('x' * 512).encode(),  # encode to bytes
                app_engine_routing=dict(
                    service='py3',
                    version='txtaskhandler',
                ),
                headers=dict(
                    TXID=tx_id,
                ),
            ),
        )
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
