const benchmark = require('./benchmark').benchmark;

exports.runBenchmark = (req, res) => {
    const project = req.query.project;
    const service = req.query.service;
    const ver = req.query.version;
    const test = req.query.test;
    const secs = +(req.query.secs || 0);
    const numConns = +(req.query.c || 64);
    if (!project || !ver || !service || !test || secs <= 0 || numConns <= 0) {
        res.status(400).send('missing required param');
        return;
    }
    benchmark(project, service, ver, test, numConns, secs, true).then(out => {
        res.send(out);
    }, err => {
        res.status(500).send('failed: ' + err);
    });
};
