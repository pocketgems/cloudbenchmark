#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
from collections import namedtuple
import re
import sys

from requests_futures.sessions import FuturesSession

ALL_TESTS = ('noop', 'sleep', 'data', 'memcache', 'dbtx', 'txtask')
NARROW_TESTS = ('noop', 'memcache', 'dbtx', 'txtask')
ICLASSES = ('f1', 'f2', 'f4')
BENCHMARKER_URL_FMT = (
    'https://us-central1-%s.cloudfunctions.net'
    '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&version=%s&c=%s')

PendingRequest = namedtuple('PendingRequest', ('url', 'future'))


PY3_ENTRY_TYPES_FOR_WSGI = (
    'gunicorn-default',

    'gunicorn-thread1w80t',
    'gunicorn-thread1w10t',
    'uwsgi-thread1w80t',
    'uwsgi-thread1w10t',

    'gunicorn-gevent1w80c',
    'uwsgi-gevent1w80c',
    #'gunicorn-meinheld1w',
)
PY3_ENTRY_TYPES_FOR_ASGI = (
    'fastapi-gunicorn-uvicorn1w',
    'fastapi-gunicorn-uvicorn-ctpe1w',
)


def get_responses(urls):
    """Fetches each URL in parallel. Failures are retried."""
    session = FuturesSession(max_workers=len(urls))
    pending = [PendingRequest(url, session.get(url)) for url in urls]
    resps = {}
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


def is_version_ignored(limit_to_versions, version):
    if limit_to_versions is None:
        return False
    for regex in limit_to_versions:
        if regex.search(version):
            return False
    return True


def add_if_needed(urls, limit_to_versions,
                  project, secs, test, service, version, num_conns):
    if not is_version_ignored(limit_to_versions, version):
        urls.append(BENCHMARKER_URL_FMT % (
            project, project, secs, test, service, version, num_conns))


def make_test_urls(project, tests, secs, num_conns, limit_to_versions):
    """Returns a list of URLs for running benchmarks."""
    urls = []
    service = 'py27'
    for test in tests:
        for icls in ICLASSES:
            for framework in ('webapp',):
                version = '%s-%s-solo-%s' % (framework, icls, test)
                add_if_needed(urls, limit_to_versions, project, secs, test,
                              service, version, num_conns)
    service = 'py37'
    to_try = []
    for framework in ('falcon', 'flask'):
        to_try.extend(['%s-%s' % (framework, x)
                       for x in PY3_ENTRY_TYPES_FOR_WSGI])
    to_try.extend(PY3_ENTRY_TYPES_FOR_ASGI)
    for test in tests:
        for framework_and_entrypoint in to_try:
            version = '%s-%s' % (framework_and_entrypoint, test)
            add_if_needed(urls, limit_to_versions, project, secs, test,
                          service, version, num_conns)
    service = 'node10'
    for test in tests:
        for framework in ('express', 'fastify',):
            version = '%s-f1-solo-%s' % (framework, test)
            add_if_needed(urls, limit_to_versions, project, secs, test,
                          service, version, num_conns)
    return urls


def main():
    """Runs tests and displays results."""
    project = sys.argv[-3]
    if ':' in project:
        project, limit_to_versions = project.split(':')
        limit_to_versions = [re.compile(x)
                             for x in limit_to_versions.split(',')]
    else:
        limit_to_versions = None

    test = sys.argv[-2]
    secs = int(sys.argv[-1])
    if test != 'all':
        tests = [test]
    else:
        tests = ALL_TESTS

    # warmup and try to measure the best latency while handling only 1 request
    # at a time
    short_test_urls = make_test_urls(project, tests, 10, 1, limit_to_versions)
    print 'warming up %d versions ...' % len(short_test_urls)
    best_resps = get_responses(short_test_urls)

    # run longer tests to gauge throughput under load (10% more connections
    # than the maximum concurrent requests allowed by the instance to ensure we
    # saturate it)
    print 'running the full tests ...'
    resps = get_responses(make_test_urls(project, tests, secs, 88,
                                         limit_to_versions))

    # print the test results, using the best performing request for min latency
    for i, resp in enumerate(resps):
        best_resp = best_resps[i]
        if not resp[5] or (resp[5] > best_resp[5] and best_resp[5]):
            resp[5] = best_resp[5]  # replace best latency
        print '\t'.join(resp)


if __name__ == '__main__':
    main()
