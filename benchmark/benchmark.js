#!/usr/bin/env node
const autocannon = require('autocannon');

async function benchmark(projectName, service, version, testName,
                         numConnections, durationSecs, numRequests,
                         isSummaryDesired) {
    var url = ['https://', version, '-dot-', service, '-dot-', projectName,
               '.appspot.com/test/' + testName].join('');
    if (testName === 'json') {
        url = url.replace('/test/json', '/test/dbjson?b=1');
    }
    if (testName.substring(0, 3) === 'ndb') {
        // same url path as db (test URL differs only in version, not path)
        url = url.replace('/test/ndb', '/test/db');
    }
    var out = await autocannon({
        amount: numRequests,
        connections: numConnections,
        duration: durationSecs,
        excludeErrorStats: true,
        pipelining: 1,
        url: url
    });
    out.service = service;
    out.version = version;
    out.testName = testName;
    out.conns = numConnections;
    if (isSummaryDesired) {
        return summarize(out);
    }
    return out;
}

// convert result dict to a tab-separated string (for copy/pasting into a
// spreadsheet)
function summarize(result) {
    return [
        result.finish.toUTCString(),
        result.service,
        result.version,
        result.testName,
        result['2xx'] / result.duration,
        result.throughput.mean / 1000,
        result.latency.min,
        result.latency.p50,
        result.latency.p90,
        result.latency.p99,
        result.non2xx,
        result.duration,
        result.non2xx / result.requests.total,
        result.errors,
    ].join('\t');
};

// can run the tests locally (but better to use
async function main(projectName, service, version, testName, duration,
                    numRequests) {
    if (!projectName || !service || !version || !testName || !duration) {
        throw 'missing required command-line arg(s)';
    }
    var out = await benchmark(projectName, service, version,
                              testName, 64, duration, numRequests);
    console.log(service, version, out.requests.mean, out.latency.p50);

    // display results in a tabular format which can be copied/pasted into a
    // spreadsheet
    console.log(['Time', 'Service', 'Version', 'Test', 'Req/sec', 'kB/sec',
                 'Latency (best, ms)',
                 'Latency p50', 'Latency p90', 'Latency p99',
                 '# Errors', 'Test Duration (s)', '% Errors',
                 'Timeouts'].join('\t'));
    console.log(summarize(out));
}

if (require.main === module) {
    main.apply(null, process.argv.slice(process.argv.length - 5));
}
exports.benchmark = benchmark;
