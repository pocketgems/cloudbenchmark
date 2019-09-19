#!/usr/bin/env node
const autocannon = require('autocannon');

const servicesToTest = [
    'py27f1one', 'py27f2one', 'py27f4one'
];

// put sizes in bytes and durations in milliseconds
function sanitizeUnits(d) {
    for (var k in d) {
        var v = d[k];
        if (typeof v === 'number') {
            continue;
        }
        if (v.endsWith('ms')) {
            d[k] = +v.substring(0, v.length - 2);
        }
        else if (v.endsWith('s')) {
            d[k] = 1000 * (+v.substring(0, v.length - 1));
        }
        else if (v.endsWith('m')) {
            d[k] = 60 * 1000 * (+v.substring(0, v.length - 1));
        }
        else if (v.endsWith('KB')) {
            d[k] = 1024 * (+v.substring(0, v.length - 2));
        }
        else if (v.endsWith('MB')) {
            d[k] = 1024 * 1024 * (+v.substring(0, v.length - 2));
        }
    }
    return d;
}

function hrTimeToMillis(hrTime) {
    return hrTime[0] * 1000 + hrTime[1] / 1000000;
}

async function benchmark(projectName, service, testName,
                         numConnections, durationSecs, isSummaryDesired) {
    var url = ['https://', service, '-dot-', projectName,
               '.appspot.com/test/' + testName].join('');

    // find best of 10 sequential requests (warms up the instance and tries to
    // get a rough estimate of best possible performance with no overhead from
    // competing requests)
    const NUM_LONE_SAMPLES = 10;
    var bestMillis = 9999999;
    for (var i = 0; i < NUM_LONE_SAMPLES; i++) {
        var start = process.hrtime();
        let { response, body } = await request.get(url);
        var end = hrTimeToMillis(process.hrtime());
        if (response.statusCode === 200) {
            start = hrTimeToMillis(start);
            var millisElapsed = end - start;
            bestMillis = Math.min(millisElapsed, bestMillis);
        }
    }

    var out = await autocannon({
        connections: numConnections,
        duration: durationSecs,
        pipelining: 1,
        url: url
    });
    out.service = service;
    out.testName = testName;
    out.conns = numConnections;
    out.bestMillis = bestMillis;
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
        result.testName,
        result.requests.mean,
        result.throughput.mean / 1000,
        result.bestMillis,
        result.latency.p50,
        result.latency.p90,
        result.latency.p99,
        result.errors,
        result.duration,
        result.non2xx / result.requests.total,
        result.requests.timeouts,
    ].join('\t');
};

async function main(projectName, testName, duration) {
    if (!projectName || !testName || !duration) {
        throw 'missing required command-line arg(s)';
    }

    // test each service sequentially
    var serviceIdx = 0;
    var results = [];
    for (var i = 0; i < servicesToTest.length; i++) {
        var service = servicesToTest[serviceIdx++];
        var out = await benchmark(projectName, service, testName, 64, duration);
        console.log(service, out.requests.mean, out.latency.p50);
        results.push(out);
    }

    // display results in a tabular format which can be copied/pasted into a
    // spreadsheet
    console.log(['Time', 'Service', 'Test', 'Req/sec', 'kB/sec',
                 'Latency (best of 10)',
                 'Latency p50 (ms)', 'Latency p90', 'Latency p99',
                 '# Errors', 'Test Duration (s)', '% Errors',
                 'Timeouts'].join('\t'));
    for (var i in results) {
        console.log(summarize(results[i]));
    }
}

if (require.main === module) {
    main.apply(null, process.argv.slice(process.argv.length - 3));
}
exports.benchmark = benchmark;
