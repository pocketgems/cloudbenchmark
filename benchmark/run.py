#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
import sys
import time

from requests_futures.sessions import FuturesSession

project = sys.argv[-3]
test = sys.argv[-2]
secs = int(sys.argv[-1])
if test != 'all':
    tests = [test]
else:
    tests = ['noop', 'sleep', 'data', 'cache', 'memcache', 'dbtx', 'txtask']
NUM_CONNS = 75
ICLASSES = ('f1', 'f2', 'f4')

fmt = ('https://us-central1-%s.cloudfunctions.net'
       '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&c=%s')

session = FuturesSession(max_workers=len(tests) * len(ICLASSES))

# warmup and try to measure the best latency while handling only 1 request at a
# time
futures = []
for test in tests:
    for icls in ICLASSES:
        service = 'py27-%s-solo-%s' % (icls, test)
        url = fmt % (project, project, 10, test, service, 1)
        futures.append(session.get(url))
print len(futures), 'single-connection warmups running'
best_resps = [f.result().content.split('\t') for f in futures]

# run longer tests to gauge throughput under load
futures = []
for test in tests:
    for icls in ICLASSES:
        service = 'py27-%s-solo-%s' % (icls, test)
        url = fmt % (project, project, secs, test, service, NUM_CONNS)
        futures.append(session.get(url))
print len(futures), 'tests running'
resps = [f.result().content.split('\t') for f in futures]

# print the test results, using the best performing request for min latency
for i, resp in enumerate(resps):
    best_resp = best_resps[i]
    print resp[5], '-->', best_resp[5]
    if resp[5] > best_resp[5]:
        resp[5] = best_resp[5]  # replace best latency
    print '\t'.join(resp)
