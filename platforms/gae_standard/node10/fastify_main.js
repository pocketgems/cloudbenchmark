const fastify = require('fastify')({
    logger: process.env.NODE_ENV !== 'production'
});
const helper = require('./helper');

fastify.get('/_ah/warmup', async (req, reply) => {
    reply.send();
});

fastify.get('/test/log', async (req, reply) => {
    console.log('hello world');
    reply.send();
});

fastify.get('/test/noop', async (req, reply) => {
    reply.send();
});


fastify.get('/test/sleep', async (req, reply) => {
    const s = +req.query.s || 1;
    await helper.sleep(s);
    reply.send();
});

fastify.get('/test/data', async (req, reply) => {
    const sz = +req.query.sz || Math.pow(2, 20);
    reply.send('x'.repeat(sz));
});

fastify.get('/test/memcache', async (req, reply) => {
    const n = +req.query.n || 1;
    const sz = +req.query.sz || 10240;
    await helper.doMemcache(n, sz);
    reply.send();
});

fastify.get('/test/dbtx', async (req, reply) => {
    const n = +req.query.n || 5;
    await helper.doDatastoreTx(n);
    reply.send();
});

fastify.get('/test/txtask', async (req, reply) => {
    const n = +req.query.n || 5;
    await helper.doTxTask(n);
    reply.send();
});

const start = async () => {
  try {
      await fastify.listen(process.env.PORT || 8080);
      fastify.log.info(`server listening on ${fastify.server.address().port}`)
  } catch (err) {
      fastify.log.error(err);
      process.exit(1);
  }
}
start();
