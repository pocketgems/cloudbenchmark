# import helper first: it monkey-patches I/O if needed
from helper import APP_ID, do_db_json, do_memcache, log

import logging
import os
import time
import traceback

from flask import Flask, request, Response
from google.cloud import datastore as db
from werkzeug.exceptions import InternalServerError

if 'ndb' in os.environ.get('GAE_VERSION', ''):
    from helper_ndb import do_db_indir_sync, do_db_indirb, do_db_tx, do_tx_task
else:
    from helper_db import do_db_indir_sync, do_db_indirb, do_db_tx, do_tx_task


app = Flask(__name__)


@app.errorhandler(InternalServerError)
def handle_500(e):
    original = getattr(e, 'original_exception', None)
    if original is None:
        # direct 500 error, such as abort(500)
        return 'direct 500 error', 500
    # unhandled error
    log(logging.ERROR, traceback.format_exc(original))
    return '', 500


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
    do_memcache(int(request.args.get('n', 10)),
                int(request.args.get('sz', 10240)))
    return ''


@app.route('/test/dbtx')
def DbTxAPI():
    """Does `n` sequential datastore transactions. No contention."""
    do_db_tx(int(request.args.get('n', 5)))
    return ''


@app.route('/test/txtask')
def TxTaskAPI():
    """Enqueues a tx task."""
    do_tx_task(int(request.args.get('n', 5)))
    return ''


@app.route('/handleTxTask', methods=['POST'])
def handle_tx_task():
    tx_id = request.headers['TXID']
    with dbc.transaction():
        key = dbc.key('TxDoneSentinel', tx_id)
        sentinel = dbc.get(key)
        if not sentinel:
            MAX_REQUEST_DURATION_SECS = 60  # on GAE standard
            # TODO: if task create time > MAX_REQUEST_DURATION_SECS ago then
            #       the tx failed but wasn't able to dequeue it; can give up
            # else: tx may not have finished yet; wait for it
            # TODO: re-enqueue this task to run again later (e.g., in 1sec)
            return ''
        else:
            db.delete(key)
            # TODO: do the tx task work
    # we could put something in redis to flag that tx task was recently handled
    # in case this task tries to re-run ... but it's a bit faster to not do
    # that, which makes sense because tasks very rarely run more than once.
    return ''


@app.route('/test/dbjson')
def DbJsonAPI():
    return str(do_db_json(bool(request.args.get('b', False))))


@app.route('/test/dbindir')
def DbIndirAPI():
    return do_db_indir_sync(int(request.args.get('n', 3)))


@app.route('/test/dbindirb')
def DbIndirbAPI():
    return do_db_indirb(int(request.args.get('n', 3)))


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=8080, debug=True)
