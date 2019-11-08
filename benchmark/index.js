const benchmark = require('./benchmark').benchmark;

exports.handler = async (event) => {
    const project = event.project;
    const nossl = !!event.nossl;
    const hostname = event.hostname;
    const service = event.service;
    const ver = event.version;
    const test = event.test;
    const secs = event.secs ? +event.secs : undefined;
    const numConns = +(event.c || 64);
    const numRequests = event.n ? +event.n : undefined;
    if (!project || (!ver && !hostname) || !service || !test ||
            (!numRequests && !secs) ||
            numConns <= 0) {
        var error = new Error('missing required param');
        error.code = 400;
        throw error;
    }
    return await benchmark(project, nossl, hostname, service, ver, test,
                           numConns, secs, numRequests, true,
                           event.isAWS);
};

exports.runBenchmark = (req, res) => {
    exports.handler(req.query).then(out => {
        res.send(out);
    }, err => {
        res.status(err.code || 500).send('failed: ' + err.message);
    });
};
