#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
from collections import namedtuple
import sys

from requests_futures.sessions import FuturesSession

ALL_TESTS = ['noop', 'sleep', 'data', 'cache', 'memcache', 'dbtx', 'txtask']
ICLASSES = ('f1', 'f2', 'f4')
BENCHMARKER_URL_FMT = (
    'https://us-central1-%s.cloudfunctions.net'
    '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&c=%s')

PendingRequest = namedtuple('PendingRequest', ('url', 'future'))

session = FuturesSession(max_workers=len(ALL_TESTS) * len(ICLASSES))


def get_responses(urls):
    """Fetches each URL in parallel. Failures are retried."""
    pending = [PendingRequest(url, session.get(url)) for url in urls]
    resps = {}
    print 'running %d benchmarks' % len(pending)
    while pending:
        new_pending = []
        for url, future in pending:
            resp = future.result()
            if resp.status_code < 200 or resp.status_code >= 300:
                new_pending.append(PendingRequest(url, session.get(url)))
            else:
                resps[url] = future.result().content.split('\t')
        pending = new_pending
        if new_pending:
            print '  %d failures to retry (%s)' % (
                len(new_pending), ' ; '.join(x[0] for x in new_pending))
    return [resps[url] for url in urls]


def make_test_urls(project, tests, secs, num_conns):
    """Returns a list of URLs for running benchmarks."""
    urls = []
    for test in tests:
        for icls in ICLASSES:
            service = 'py27-%s-solo-%s' % (icls, test)
            urls.append(BENCHMARKER_URL_FMT % (
                project, project, secs, test, service, num_conns))
    return urls


def main():
    """Runs tests and displays results."""
    project = sys.argv[-3]
    test = sys.argv[-2]
    secs = int(sys.argv[-1])
    if test != 'all':
        tests = [test]
    else:
        tests = ALL_TESTS

    # warmup and try to measure the best latency while handling only 1 request
    # at a time
    best_resps = get_responses(make_test_urls(project, tests, 10, 1))

    # run longer tests to gauge throughput under load (10% more connections
    # than the maximum concurrent requests allowed by the instance to ensure we
    # saturate it)
    resps = get_responses(make_test_urls(project, tests, secs, 88))

    # print the test results, using the best performing request for min latency
    for i, resp in enumerate(resps):
        best_resp = best_resps[i]
        if not resp[5] or (resp[5] > best_resp[5] and best_resp[5]):
            resp[5] = best_resp[5]  # replace best latency
        print '\t'.join(resp)


if __name__ == '__main__':
    main()
