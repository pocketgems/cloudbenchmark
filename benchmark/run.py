#!/usr/bin/env python
"""The script runs orchestrates the running of benchmarks in parallel."""
import argparse
from collections import defaultdict, namedtuple
import datetime
import os
import re
import subprocess
import threading
import time

import requests

TESTS = set([
    'noop', 'sleep', #'data',
    'memcache', 'dbtx', 'txtask',
    'dbindir', 'dbindirb', 'dbjson'
])
PY3TESTS = TESTS | set(['ndbtx', 'ndbtxtask', 'ndbindir', 'ndbindirb'])
CLOUD_RUN_MACHINE_TYPES = ('managed',
                           'n1-highcpu-2', 'n2-highcpu-2', 'c2-standard-4')
ICLASSES = ('f1', 'f2', 'f4')
BENCHMARKER_URL_FMT = (
    'https://us-central1-%s.cloudfunctions.net'
    '/runBenchmark?project=%s&secs=%d&test=%s&service=%s&version=%s&c=%s')

PendingRequest = namedtuple('PendingRequest', ('url', 'future'))
Benchmark = namedtuple('Benchmark', ('service', 'version', 'test'))
CloudRunBenchmark = namedtuple('CloudRunBenchmark', (
    'service', 'base_url', 'test'))
DEVNULL = open(os.devnull, 'w')
FILE_LOCK = threading.Lock()
PRINT_LOCK = threading.Lock()
SHUTDOWN_LOCK = threading.Lock()
KILL_FLAG = False


PY3_ENTRY_TYPES_FOR_WSGI = (
    'gunicorn-default',

    'gunicorn-thrd1w80t',
    'gunicorn-thrd1w10t',
    'uwsgi-thread1w80t',
    'uwsgi-thread1w10t',

    'gunicorn-gevent1w',
    'uwsgi-gevent1w80c',
    # 'gunicorn-meinheld1w',
)
PY3_ENTRY_TYPES_FOR_ASGI = (
    #'fastapi-gunicorn-uvicorn1w',
    'fastapi-gunicorn-uv2-1w',
)


def is_version_ignored(limit_to_versions, version):
    """Returns True if the version should not be benchmarked."""
    if not limit_to_versions:
        return False
    for regex in limit_to_versions:
        if regex.search(version):
            return False
    return True


def tt(test):
    """Transform test name to name used in the version.

    dbjson and json share a version. Don't run them at the same time.
    """
    if test == 'json':
        return 'dbjson'
    return test


CR_URLS = None

def get_managed_cloud_run_url(service):
    """Returns the URL for accessing a managed Cloud Run service."""
    global CR_URLS  # pylint: disable=global-statement
    if not CR_URLS:
        out = {}
        ret = subprocess.check_output([
            'gcloud', 'beta', 'run', 'services', 'list',
            '--platform', 'managed',
            '--format', 'csv(metadata.name,status.address.url)'])
        for line in ret.split('\n')[1:]:
            if not line:
                continue
            service_id, url = line.split(',')
            if url:
                out[service_id] = url
        CR_URLS = out
    return CR_URLS[service]


def get_benchmarks(tests, limit_to_versions):
    """Returns a list of benchmarks to run."""
    greenlit = []
    for machine_type in CLOUD_RUN_MACHINE_TYPES:
        if machine_type != 'managed':
            ip_fn = 'platforms/cloud_run/clusterip_%s.txt' % machine_type
            if not os.path.exists(ip_fn):
                continue  # cluster not setup
            cluster_ip = open(ip_fn, 'r').read().strip()
        for test in tests & TESTS:
            for runtime in ('node10', 'py3', 'pypy3'):
                if runtime == 'node10':
                    kinds = ['express', 'fastify']
                else:
                    kinds = [
                        'gunicorn-gevent',
                        'gunicorn-gthread',
                        'gunicorn-uvicorn',
                    ]
                    if runtime != 'pypy3':
                        kinds.append('uwsgi-gevent')
                for kind in kinds:
                    service = '%s-%s-%s-%s' % (machine_type, runtime, kind, test)
                    if machine_type == 'managed':
                        base_url = get_managed_cloud_run_url(service)
                    else:
                        base_url = 'http://' + cluster_ip
                    if not is_version_ignored(limit_to_versions, service):
                        greenlit.append(CloudRunBenchmark(
                            service, base_url, test))
    # GAE
    service = 'py27'
    for test in tests & TESTS:
        for icls in ICLASSES:
            for framework in ('webapp',):
                version = '%s-%s-solo-%s' % (framework, icls, tt(test))
                if not is_version_ignored(limit_to_versions, version):
                    greenlit.append(Benchmark(service, version, test))
    service = 'py37'
    to_try = []
    for framework in ('falcon', 'flask'):
        to_try.extend(['%s-%s' % (framework, x)
                       for x in PY3_ENTRY_TYPES_FOR_WSGI
                       # no uwsgi tests for flask
                       if 'uwsgi' not in x or framework != 'flask'])
    to_try.extend(PY3_ENTRY_TYPES_FOR_ASGI)
    for test in tests & PY3TESTS:
        for framework_and_entrypoint in to_try:
            if 'flask' in framework_and_entrypoint and test  not in TESTS:
                continue  # only standard tests for flask
            version = '%s-%s' % (framework_and_entrypoint, tt(test))
            if not is_version_ignored(limit_to_versions, version):
                greenlit.append(Benchmark(service, version, test))
    service = 'node10'
    for test in tests & TESTS:
        for framework in ('express', 'fastify',):
            version = '%s-f1-solo-%s' % (framework, tt(test))
            if not is_version_ignored(limit_to_versions, version):
                greenlit.append(Benchmark(service, version, test))
    return greenlit


def run_benchmarks(results_fn, project, secs, left_by_benchmark):
    """Runs each benchmark the specified number of times.

    Results will be saved to results_fn (if provided). Otherwise results
    will be printed to stdout.
    """
    global KILL_FLAG  # pylint: disable=global-statement
    threads = [
        threading.Thread(target=run_benchmark, kwargs=dict(
            benchmark=benchmark,
            secs=secs,
            project=project,
            num_left=num_left,
            results_fn=results_fn))
        for benchmark, num_left in left_by_benchmark.iteritems()]
    start_needed = True
    threads_left = []
    prev_num_left = None
    while start_needed or threads_left:
        try:
            if start_needed:
                start_needed = False
                for thread in threads:
                    threads_left.append(thread)
                    thread.start()
            else:
                for thread in threads_left[:]:
                    thread.join(timeout=0)
                    if not thread.is_alive():
                        threads_left.remove(thread)
            if threads_left:
                if KILL_FLAG:
                    if len(threads_left) != prev_num_left:
                        prev_num_left = len(threads_left)
                        log('    still waiting on %d threads ...',
                            prev_num_left)
                time.sleep(3)
        except (KeyboardInterrupt, SystemExit):
            if not KILL_FLAG:
                KILL_FLAG = True
                prev_num_left = len(threads_left)
                log('\nShutting down: %d threads left ...', prev_num_left)


def run_benchmark(benchmark, secs, project, num_left, results_fn):
    """Runs a single benchmark the specified number of times."""
    service = benchmark.service
    test = benchmark.test
    version = getattr(benchmark, 'version', '')  # only present for GAE bmarks
    is_gae = bool(version)

    one_request_benchmarker_url = BENCHMARKER_URL_FMT % (
        project, project, 60, 'noop', service, version, 1) + '&n=1'
    full_test_benchmarker_url = BENCHMARKER_URL_FMT % (
        project, project, secs, test, service, version,
        # dbjson is a memory (and cpu) hog, so we can max it out and not blow
        # up memory by limiting connections
        88 if 'json' not in test else 2)

    if is_gae:
        cmd = 'gcloud app instances %%s --service %s --version %s' % (
            service, version)
        list_cmd = (cmd % 'list').split()
        delete_cmd = ((cmd % 'delete') + ' --quiet').split()
    else:
        base_url = benchmark.base_url
        scheme, hostname = base_url.split('://', 1)
        extra_qs = '&hostname=' + hostname
        if scheme == 'http':
            extra_qs += '&nossl=1'
        one_request_benchmarker_url += extra_qs
        full_test_benchmarker_url += extra_qs

    context = 'service=%-6s version=%-36s test=%-7s    ' % (
        service, version, test)
    pad_sz = max(0, 76 - len(context))
    if pad_sz:
        context += (' ' * pad_sz)
    my_log = lambda s, *args: log(context + s, *args)
    while num_left > 0 and not KILL_FLAG:
        try:
            if is_gae:
                # shut down the current instance, if any
                my_log('listing instances')
                out = subprocess.check_output(list_cmd, stderr=DEVNULL)
                if out:
                    rows = out.split('\n')
                    iid_idx = rows[0].split().index('ID')
                    iid = rows[1].split()[iid_idx]
                    my_log('shutting down %s', iid)
                    with SHUTDOWN_LOCK:
                        subprocess.check_call(delete_cmd + [iid],
                                              stderr=DEVNULL, stdout=DEVNULL)
                    my_log('shuttdown down %s', iid)

            # measure time for a single request to be served (startup latency)
            # note: this request is for the no-op url (not measuring processing
            #       time here, just startup time)
            my_log('warming up')
            resp = requests.get(one_request_benchmarker_url)
            if resp.status_code != 200:
                raise Exception('got HTTP %d error' % resp.status_code)
            x = resp.content.split('\t')
            if int(x[10]) or int(x[13]):
                raise Exception('initial request failed: %s' % resp.content)
            startup_millis = x[6]
            if is_gae or startup_millis > 10000:
                my_log('started in %s', startup_millis)
            else:
                startup_millis = -1  # CR service was probably already started

            # dbjson test requires a special request to first load the JSON
            # data from disk
            if 'json' in test:
                dbjson_url = one_request_benchmarker_url.replace(
                    '/test/noop', '/test/dbjson')
                requests.get(dbjson_url)  # ignore response
                resp = requests.get(dbjson_url)
                if resp.status_code != 200:
                    raise Exception(
                        'got HTTP %d error while preparing %s' % (
                            resp.status_code, test))

            # run the benchmark
            resp = requests.get(full_test_benchmarker_url)
            if resp.status_code != 200:
                raise Exception('got HTTP %d error' % resp.status_code)
            results_line = resp.content + '\t' + startup_millis
            my_log('%d left; output: %s', num_left - 1, results_line)

            # record the results
            if results_fn:
                with FILE_LOCK:
                    with open(results_fn, 'a', buffering=0) as fout:
                        print >> fout, results_line
            num_left -= 1
        except Exception, e:  # pylint: disable=broad-except
            log('EXCEPTION in thread (%s): %s', context, e)


def log(s, *args):
    """Prints to standard out. A lock synchronizes thread output."""
    if args:
        s = s % args
    now = datetime.datetime.now().strftime('%H:%M:%S')
    with PRINT_LOCK:
        print now, s


def main():
    """Runs tests and displays results."""
    parser = argparse.ArgumentParser()
    parser.add_argument('PROJECT', help='GCP project ID')
    parser.add_argument('--filter', action='append', dest='filters',
                        help='regex of services to include')
    parser.add_argument('-n', type=int, help='# of times to run each test',
                        default=1)
    parser.add_argument('--continue', dest='results_fn',
                        help='file to save results & pick up from if resuming')
    parser.add_argument('--secs', type=int, help='how long to run test',
                        default=60)
    parser.add_argument('--dry-run', action='store_true',
                        help='if passed, benchmarks will be printed, not run')
    parser.add_argument('--test', action='append', dest='tests',
                        choices=PY3TESTS,
                        help='which test to run (omit to run all tests)')
    args = parser.parse_args()
    limit_to_versions = [
        re.compile(x) for x in args.filters] if args.filters else None
    secs = args.secs
    assert args.secs > 0
    assert args.secs <= 290  # limited to 5min runtime on cloud functions
    tests = set(args.tests or PY3TESTS)
    num_runs = args.n
    assert num_runs >= 1

    # figure out which benchmarks this test includes
    benchmarks = get_benchmarks(tests, limit_to_versions)
    print '%d benchmarks to run (%d times each)' % (
        len(benchmarks), num_runs)
    if args.dry_run:
        for x in benchmarks:
            print x
        return
    time.sleep(3)

    # figure out how many runs if each test is needed
    completed_count = defaultdict(int)
    if args.results_fn:
        if not os.path.exists(args.results_fn):
            open(args.results_fn, 'w').write('')
        try:
            results = open(args.results_fn, 'r').read().split('\n')
        except:  # pylint: disable=bare-except
            print 'no results yet'
            results = []
        for line in results:
            if not line:
                continue
            pieces = line.split('\t')
            uid = Benchmark(*pieces[1:4])
            completed_count[uid] += 1
    num_left = dict((benchmark, max(0, num_runs - completed_count[benchmark]))
                    for benchmark in benchmarks)
    tot_left = sum(num_left.itervalues())
    num_done = len(benchmarks) * num_runs - tot_left
    if num_done:
        print '    %d left (%d already done)' % (tot_left, num_done)
    run_benchmarks(args.results_fn, args.PROJECT, secs, num_left)


if __name__ == '__main__':
    main()
