# if running uwsgi+gevent (ONLY) then we need to monkeypatch because it doesn't
# monkey-patch for us
if 'uwsgi-gevent' in os.environ.get('GAE_SERVICE', ''):
    import gevent.monkey
    gevent.monkey.patch_all()


import os
APP_ID = os.environ.get('GAE_APPLICATION', '').replace('s~', '')
if __name__ != '__main__':
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
    import logging
    def log(severity, msg, *args):
        logging.log(severity, msg, *args)


import time
import traceback
import uuid

from flask import Flask, request, Response
from google.cloud import datastore as db, tasks_v2
import redis
from werkzeug.exceptions import InternalServerError

app = Flask(__name__)
app.debug = True


@app.errorhandler(InternalServerError)
def handle_500(e):
    original = getattr(e, 'original_exception', None)
    if original is None:
        # direct 500 error, such as abort(500)
        return 'direct 500 error', 500
    # unhandled error
    log(logging.ERROR, traceback.format_exc(original))
    return '', 500


dbc = db.Client()
if 'REDIS_HOST' in os.environ:
    rcache = redis.Redis(host=os.environ['REDIS_HOST'],
                         port=int(os.environ['REDIS_PORT']))
else:
    log(logging.WARN, 'missing redis creds')
taskq = tasks_v2.CloudTasksClient.from_service_account_json(
    'cloudtasksaccount.json')
MAX_REQUEST_DURATION_SECS = 60  # on GAE standard


@app.route('/_ah/warmup')
def WarmupAPI():
    return ''


@app.route('/test/log')
def TestLogsAPI():
    log(logging.CRITICAL, 'hello world')
    return ''


@app.route('/test/noop')
def NoOpAPI():
    return ''


@app.route('/test/sleep')
def SleepAPI():
    """Sleeps for `s` seconds."""
    time.sleep(float(request.args.get('s', 1)))
    return ''


@app.route('/test/data')
def GetFakeDataAPI():
    """Returns `sz` bytes of junk data."""
    return 'x' * int(request.args.get('sz', 2**20))


@app.route('/test/cache')
def CachedAPI():
    """Sets cache-control header."""
    data = 'x' * int(request.args.get('sz', 2**20))
    resp = Response(data)
    resp.headers['Cache-Control'] = 'max-age=360, public'
    return resp


@app.route('/test/memcache')
def MemcacheAPI():
    """Puts `sz` bytes into memcache and gets it `n` times sequentially."""
    key = uuid.uuid4().hex
    val = b'x' * int(request.args.get('sz', 10240))
    rcache.set(key, val, ex=60)
    for ignore in range(int(request.args.get('n', 10))):
        assert rcache.get(key) == val
    return ''


@app.route('/test/dbtx')
def DbTxAPI():
    """Does `n` sequential datastore transactions. No contention."""
    for ignore in range(int(request.args.get('n', 5))):
        random_id = uuid.uuid4().hex
        with dbc.transaction():
            dbc.put(incr_db_entry(random_id))
    return ''


@app.route('/test/txtask')
def TxTaskAPI():
    """Enqueues a tx task."""
    for ignore in range(int(request.args.get('n', 5))):
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
                    service='py3taskhandler',
                    version='v1',
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
    return ''


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


@app.route('/handleTxTask', methods=['POST'])
def handle_tx_task():
    tx_id = request.headers['TXID']
    with dbc.transaction():
        key = dbc.key('TxDoneSentinel', tx_id)
        sentinel = dbc.get(key)
        if not sentinel:
            # TODO: if task create time > MAX_REQUEST_DURATION_SECS ago then
            #       the tx failed but wasn't able to dequeue it; can give up
            # else: tx may not have finished yet; wait for it
            # TODO: re-enqueue this task to run again later (e.g., in 1sec)
            return
        else:
            db.delete(key)
            # TODO: do the tx task work
    # we could put something in redis to flag that tx task was recently handled
    # in case this task tries to re-run ... but it's a bit faster to not do
    # that, which makes sense because tasks very rarely run more than once.


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
