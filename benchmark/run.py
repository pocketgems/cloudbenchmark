#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
import sys

from requests_futures.sessions import FuturesSession

project = sys.argv[-3]
test = sys.argv[-2]
secs = int(sys.argv[-1])
if test != 'all':
    tests = [test]
else:
    tests = ['noop', 'sleep', 'data', 'cache', 'memcache', 'db_tx', 'tx_task']

fmt = ('https://us-central1-%s.cloudfunctions.net'
       '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&c=75')

session = FuturesSession(max_workers=16)
for test in tests:
    futures = []
    for icls in ('f1', 'f2', 'f4'):
        service = 'py27%sone' % icls
        url = fmt % (project, project, secs, test, service)
        futures.append(session.get(url))
    # wait for test to finish before starting the next one (only one machine
    # per service so we can test individual machine capacity)
    print test
    for future in futures:
        print future.result().content
