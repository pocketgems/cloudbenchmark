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
    tests = ['noop', 'sleep', 'data', 'cache', 'memcache', 'db_tx', 'tx_task']
NUM_CONNS = 75

fmt = ('https://us-central1-%s.cloudfunctions.net'
       '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&c=%s')

session = FuturesSession(max_workers=16)
for test in tests:
    futures = []
    for icls in ('f1', 'f2', 'f4'):
        service = 'py27%sone' % icls
        url = fmt % (project, project, secs, test, service, NUM_CONNS)
        futures.append(session.get(url))
    # wait for test to finish before starting the next one (only one machine
    # per service so we can test individual machine capacity)
    print test
    resps = [f.result().content.split('\t') for f in futures]
    time.sleep(1.0)  # a little pause to ensure the instance is idle
    # measure best single latency too
    futures = []
    for icls in ('f1', 'f2', 'f4'):
        service = 'py27%sone' % icls
        url = fmt % (project, project, 10, test, service, 1)
        futures.append(session.get(url))
    best_resps = [f.result().content.split('\t') for f in futures]
    for i, resp in enumerate(resps):
        best_resp = best_resps[i]
        print resp[5], '-->', best_resp[5]
        resp[5] = best_resp[5]  # replace best latency
        print '\t'.join(resp)
