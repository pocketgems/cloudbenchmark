import random
import time
import uuid
import zlib

from google.appengine.api import memcache, taskqueue
from google.appengine.ext import ndb
import ujson
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
        self.response.out.write(data)


class MemcacheAPI(webapp.RequestHandler):
    """Puts `sz` bytes into memcache and gets it `n` times sequentially."""
    def get(self):
        key = uuid.uuid4().hex
        memcache.set(key, 'x' * int(self.request.get('sz', 10240)), time=60)
        for ignore in xrange(int(self.request.get('n', 10))):
            memcache.get(key)


class DbTxAPI(webapp.RequestHandler):
    """Does `n` sequential datastore transactions. No contention."""
    def get(self):
        random_id = uuid.uuid4().hex
        for ignore in xrange(int(self.request.get('n', 5))):
            self.incr(random_id)

    @staticmethod
    @ndb.transactional
    def incr(some_id):
        x = Counter.get_by_id(some_id)
        if not x:
            x = Counter(id=some_id)
        x.count += 1
        x.put()


class Counter(ndb.Model):
    count = ndb.IntegerProperty(default=0, indexed=False)


class TxTaskAPI(DbTxAPI):
    """Enqueues a tx task."""
    @staticmethod
    @ndb.transactional
    def incr(some_id):
        # run the task on another service; when benchmarking we only want to
        # measure the instance handling this API (not the tasks it generates)
        task = taskqueue.Task(url='/thisWill404', payload='x' * 512,
                              target='v1.default')
        futures = [task.add_async(queue_name='test',
                                  rpc=taskqueue.create_rpc(),
                                  transactional=True)]
        x = Counter.get_by_id(some_id)
        if not x:
            x = Counter(id=some_id)
        x.count += 1
        futures.append(x.put_async())
        for f in futures:
            f.get_result()


class LargeJsonDbAPI(webapp.RequestHandler):
    """Writes and reads a large JSON blob from the datastore (no tx)."""
    LARGE_JSON = None

    def get(self):
        if not LargeJsonDbAPI.LARGE_JSON:
            with open('big.json', 'r') as fin:
                LargeJsonDbAPI.LARGE_JSON = ujson.loads(fin.read())
            raise Exception('read from file')  # don't include in benchmark
        random_id = uuid.uuid4().hex
        BigJsonHolder(
            id=random_id,
            data=zlib.compress(ujson.dumps(LargeJsonDbAPI.LARGE_JSON))).put()
        x = BigJsonHolder.get_by_id(random_id)
        raw = zlib.decompress(x.data)
        ujson.loads(raw)
        self.response.out.write(str(len(raw)))


class BigJsonHolder(ndb.Model):
    data = ndb.BlobProperty()


class IndirDbRequestAPI(webapp.RequestHandler):
    """In parallel, get X and then another thing we "don't" know until we've
    retrieved X.
    """
    def get(self):
        n = int(self.request.get('n', 3))
        futures = [self._get_and_get_dependency() for ignore in xrange(n)]
        self.response.out.write(str(sum(f.get_result() for f in futures)))

    @ndb.tasklet
    def _get_and_get_dependency(self):
        """Gets a random OneInt. Then gets another OneInt whose key is
        double (modded to fit in the range).
        """
        x = yield self._get_random_key().get_async()
        if not x:
            raise Exception('OneInt entity missing (not yet defined?)')
        new_idx = (2 * x.key.id()) % 10000
        subx = yield ndb.Key(OneInt, new_idx).get_async()
        raise ndb.Return(subx.key.id() + x.key.id())

    @staticmethod
    def _get_random_key():
        return ndb.Key(OneInt, random.randint(0, 9999))

    # initialize the datastore entities
    def post(self):
        s = int(self.request.get('s', 0))
        n = int(self.request.get('n', 1000))
        entities = [OneInt(id=i) for i in xrange(s, s + n)]
        ndb.put_multi(entities)


class IndirBatchDbRequestAPI(webapp.RequestHandler):
    """Batched version.

    Do all of the first set of gets. Then get all their deps. Fewer
    round-trips, but blocks unnecessarily. This would almost certainly be much
    worse if one of the first set gets was long and one of the second set gets
    was long (but the two weren't paired). But when all DB gets are about
    equal (like this), it may be more efficient to batch like this.
    """
    def get(self):
        n = int(self.request.get('n', 3))
        keys = [self._get_random_key() for ignore in xrange(n)]
        entities = ndb.get_multi(keys)
        if None in entities:
            raise Exception('OneInt entity missing (not yet defined?)')
        new_keys = [ndb.Key(OneInt, (2 * x.key.id()) % 10000)
                    for x in entities]
        entities.extend(ndb.get_multi(new_keys))
        self.response.out.write(str(sum(x.key.id() for x in entities)))

    @staticmethod
    def _get_random_key():
        return ndb.Key(OneInt, random.randint(0, 9999))


class OneInt(ndb.Model):
    pass


routes = [
    ('/_ah/warmup', NoOpAPI),
    ('/test/noop', NoOpAPI),
    ('/test/sleep', SleepAPI),
    ('/test/data', GetFakeDataAPI),
    ('/test/cache', CachedAPI),
    ('/test/memcache', MemcacheAPI),
    ('/test/dbtx', DbTxAPI),
    ('/test/txtask', TxTaskAPI),
    ('/test/dbjson', LargeJsonDbAPI),
    ('/test/dbindir', IndirDbRequestAPI),
    ('/test/dbindirb', IndirBatchDbRequestAPI),
]

app = webapp.WSGIApplication(routes, debug=False)
