const benchmark = require('./benchmark').benchmark;

exports.runBenchmark = (req, res) => {
    const project = req.query.project;
    const nossl = !!req.query.nossl;
    const hostname = req.query.hostname;
    const service = req.query.service;
    const ver = req.query.version;
    const test = req.query.test;
    const secs = +(req.query.secs || 0);
    const numConns = +(req.query.c || 64);
    const numRequests = req.query.n ? +req.query.n : undefined;
    if (!project || (!ver && !hostname) || !service || !test || secs <= 0 ||
            numConns <= 0) {
        res.status(400).send('missing required param');
        return;
    }
    benchmark(project, nossl, hostname, service, ver, test, numConns, secs,
              numRequests, true).then(out => {
        res.send(out);
    }, err => {
        res.status(500).send('failed: ' + err);
    });
};
