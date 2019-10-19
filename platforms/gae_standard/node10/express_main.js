const express = require('express');
const asyncHandler = require('express-async-handler');
const helper = require('./helper');

const app = express()
app.enable('trust proxy');

app.get('/_ah/warmup', (req, res) => {
    res.end();
});

app.get('/test/log', (req, res) => {
    console.log(`hello world ${process.pid}`);
    res.end();
});

app.get('/test/noop', (req, res) => {
    res.end();
});

app.get('/test/sleep', asyncHandler(async (req, res, next) => {
    const s = +req.query.s || 1;
    await helper.sleep(s);
    res.end();
}));

app.get('/test/data', (req, res) => {
    const sz = +req.query.sz || Math.pow(2, 20);
    res.send('x'.repeat(sz));
});

app.get('/test/memcache', asyncHandler(async (req, res, next) => {
    const n = +req.query.n || 1;
    const sz = +req.query.sz || 10240;
    await helper.doMemcache(n, sz);
    res.end();
}));

app.get('/test/dbtx', asyncHandler(async (req, res, next) => {
    const n = +req.query.n || 5;
    await helper.doDatastoreTx(n);
    res.end();
}));

app.get('/test/txtask', asyncHandler(async (req, res, next) => {
    const n = +req.query.n || 5;
    await helper.doTxTask(n);
    res.end();
}));

app.get('/test/dbjson', asyncHandler(async (req, res, next) => {
    res.send(await helper.doDbJson(!!req.query.b));
}));

app.get('/test/dbindir', asyncHandler(async (req, res, next) => {
    const n = +req.query.n || 3;
    res.send(await helper.doDbIndir(n));
}));

app.get('/test/dbindirb', asyncHandler(async (req, res, next) => {
    const n = +req.query.n || 3;
    res.send(await helper.doDbIndirb(n));
}));

require('./clusterize').startApp((PORT) => {
    app.listen(PORT, () => {
        console.log(`worker PID ${process.pid} listening on port ${PORT} ...`);
    });
});
