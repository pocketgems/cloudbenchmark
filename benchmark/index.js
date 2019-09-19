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
    benchmark(projectName, service, testName, numConns, secs + 's', (err, out) => {
        if (err) {
            console.log(err);
            console.log(out);
            res.status(500).send('error: ' + err);
            return;
        }
        var finishedAt = new Date().toUTCString();
        var result = out.results;
        var numErrors = (+(result.connectErrors || 0)) +
            (+(result.readErrors || 0)) +
            (+(result.writeErrors || 0)) +
            (+(result.timeoutErrors || 0)) +
            (+(result.non2xx3xx || 0));
        var output = [
            finishedAt,
            out.service,
            out.testName,
            result.requestsPerSec,
            result.transferPerSec,
            result.latency50,
            result.latency90,
            result.latency99,
            numErrors,
            result.durationActual,
            numErrors / result.requestsTotal,
        ].join('\t');
        res.send(output);
    });
};
