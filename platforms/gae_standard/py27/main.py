import time
import uuid

from google.appengine.api import memcache, taskqueue
from google.appengine.ext import ndb
import webapp2 as webapp


class NoOpAPI(webapp.RequestHandler):
    def get(self):
        return


class SleepAPI(webapp.RequestHandler):
    """Sleeps for `s` seconds."""
    def get(self):
        time.sleep(float(self.request.get('s', 1)))


class GetFakeDataAPI(webapp.RequestHandler):
    """Returns `sz` bytes of junk data."""
    def get(self):
        self.response.out.write('x' * int(self.request.get('sz', 2**20)))


class CachedAPI(webapp.RequestHandler):
    """Sets cache-control header."""
    def get(self):
        data = 'x' * int(self.request.get('sz', 2**20))
        self.response.headers['Cache-Control'] = 'max-age=360, public'
        return data


class MemcacheAPI(webapp.RequestHandler):
    """Puts `sz` bytes into memcache and gets it `n` times sequentially."""
    def get(self):
        key = uuid.uuid4().hex
        memcache.set(key, 'x' * int(self.request.get('sz', 10240)), time=60)
        for ignore in xrange(int(self.request.get('n'))):
            memcache.get(key)


class DbTxAPI(webapp.RequestHandler):
    """Does `n` sequential datastore transactions. No contention."""
    def get(self):
        for ignore in xrange(int(self.request.get('n', 5))):
            random_id = uuid.uuid4().hex
            self.incr(random_id)

    @staticmethod
    @ndb.transactional
    def incr(some_id):
        x = Counter.get_by_id(some_id)
        if not x:
            x = Counter()
        x.count += 1
        x.put()


class Counter(ndb.Model):
    count = ndb.IntegerProperty(default=0, indexed=False)


class TxTaskAPI(DbTxAPI):
    """Enqueues a tx task."""
    @staticmethod
    @ndb.transactional
    def incr(some_id):
        task = taskqueue.Task(url='/test/task', payload='x' * 512)
        futures = [task.add_async(queue_name='test',
                                  rpc=taskqueue.create_rpc(),
                                  transactional=True)]
        x = Counter.get_by_id(some_id)
        if not x:
            x = Counter()
        x.count += 1
        futures.append(x.put_async())
        for f in futures:
            f.get_result()


routes = [
    ('/_ah/warmup', NoOpAPI),
    ('/test/noop', NoOpAPI),
    ('/test/sleep', SleepAPI),
    ('/test/data', GetFakeDataAPI),
    ('/test/cache', CachedAPI),
    ('/test/memcache', MemcacheAPI),
    ('/test/db_tx', DbTxAPI),
    ('/test/tx_task', TxTaskAPI),
]

app = webapp.WSGIApplication(routes, debug=False)
