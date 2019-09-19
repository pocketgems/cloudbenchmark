#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
import sys

from requests_futures.sessions import FuturesSession

project = sys.argv[-3]
test = sys.argv[-2]
secs = int(sys.argv[-1])

fmt = ('https://us-central1-benchmark-gcp.cloudfunctions.net'
       '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&c=64')

session = FuturesSession(max_workers=16)
futures = []
for icls in ('f1', 'f2', 'f4'):
    service = 'py27%sone' % icls
    url = fmt % (project, secs, test, service)
    futures.append(session.get(url))


resps = [f.result() for f in futures]
for future in futures:
    print future.result().content
