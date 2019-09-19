#!/usr/bin/env node
const wrk = require('wrk');

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

function benchmark(projectName, service, testName,
                   numConnections, duration, resolve) {
    var url = ['https://', service, '-dot-', projectName,
               '.appspot.com/test/' + testName].join('');
    var numThreads = Math.max(1, Math.min(16, Math.floor(numConnections / 4)));
    wrk({
        threads: numThreads,
        connections: numConnections,
        duration: duration,
        printLatency: true,
        url: url
    }, function(err, out) {
        if (!err) {
            out = {
                url: url, service: service, testName: testName,
                threads: numThreads, conns: numConnections,
                results: sanitizeUnits(out)
            };
        }
        resolve(err, out);
    });
}

function main(projectName, testName, duration) {
    if (!projectName || !testName || !duration) {
        throw 'missing required command-line arg(s)';
    }

    // test each service sequentially
    var serviceIdx = 0;
    var results = [];
    function doWork() {
        var service = servicesToTest[serviceIdx++];
        if (!service) {
            return displayResults();
        }
        benchmark(projectName, service, testName, 64, duration, function(err, out) {
            if (err) {
                throw err;
            }
            console.log(out);
            results.push(out);
            doWork();
        });
    }
    doWork();

    // display results in a tabular format which can be copied/pasted into a
    // spreadsheet
    function displayResults() {
        var finishedAt = new Date().toUTCString();
        console.log(['Time', 'Service', 'Test', 'RPS', 'bytes/sec',
                     'Latency 50th (ms)', 'Latency 90th', 'Latency 99th',
                     '# Errors', 'Test Duration (ms)'].join('\t'));
        for (var idx in results) {
            var out = results[idx];
            var result = out.results;
            console.log([
                finishedAt,
                out.service,
                out.testName,
                result.requestsPerSec,
                result.transferPerSec,
                result.latency50,
                result.latency90,
                result.latency99,
                (+(result.connectErrors || 0)) +
                    (+(result.readErrors || 0)) +
                    (+(result.writeErrors || 0)) +
                    (+(result.timeoutErrors || 0)) +
                    (+(result.non2xx3xx || 0)),
                result.durationActual,
            ].join('\t'));
        }
    }
}

if (require.main === module) {
    main.apply(null, process.argv.slice(process.argv.length - 3));
}
exports.benchmark = benchmark;
