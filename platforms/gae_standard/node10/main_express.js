const express = require('express');
const helper = require('./helper');

const app = express()
app.enable('trust proxy');

app.get('/_ah/warmup', (req, res) => {
    // no-op
});

app.get('/test/log', (req, res) => {
    console.log('hello world');
    res.end();
});

app.get('/test/noop', (req, res) => {
    res.end();
});

function sleep(secs){
    return new Promise(resolve => {
        setTimeout(resolve, secs * 1000);
    });
}
app.get('/test/sleep', (req, res) => {
    const s = +req.query.s || 1;
    sleep(s).then(() => {
        res.end();
    });
});

app.get('/test/data', (req, res) => {
    const sz = +req.query.sz || Math.pow(2, 20);
    res.send('x'.repeat(sz));
});

function genericCallbackHandler(res, err) {
    if (err) {
        res.status(500);
    }
    res.end();
}

app.get('/test/memcache', (req, res) => {
    const n = +req.query.n || 1;
    const sz = +req.query.sz || 10240;
    helper.do_memcache(n, sz, (err) => { genericCallbackHandler(res, err); });
});

app.get('/test/dbtx', (req, res) => {
    const n = +req.query.n || 5;
    helper.do_db_tx(n).then(res.end);
});

app.get('/test/txtask', (req, res) => {
    const n = +req.query.n || 5;
    helper.do_tx_task(n, (err) => { genericCallbackHandler(res, err); });
});

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
    console.log(`Server listening on port ${PORT}...`);
});
