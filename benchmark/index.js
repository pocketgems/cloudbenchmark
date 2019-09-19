const benchmark = require('./benchmark').benchmark;

exports.runBenchmark = (req, res) => {
    const projectName = req.query.project;
    const service = req.query.service;
    const testName = req.query.test;
    const secs = +(req.query.secs || 0);
    const numConns = +(req.query.c || 64);
    if (!projectName || !service || !testName || secs <= 0 || numConns <= 0) {
        res.status(400).send('missing required param');
        return;
    }
    benchmark(projectName, service, testName, numConns, secs, true).then(out => {
        res.send(out);
    }, err => {
        res.status(500).send('failed: ' + err);
    });
};
