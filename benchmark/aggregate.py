#!/usr/bin/env python3
"""The script aggregates benchmark data."""
import argparse
from collections import defaultdict, namedtuple
import statistics


Benchmark = namedtuple('Benchmark', ('service', 'version', 'test'))
Stats = namedtuple('Stats', ('avg', 'sdev', 'sz'))
AggregateResult = namedtuple('AggregateResult', (
    'test', 'service', 'version', 'rps_avg', 'rps_sd', 'l50_avg', 'l50_sd',
    'non2xx_avg', 'non2xx_sd', 'pct_err_avg', 'pct_err_sd', 'conn_err_avg',
    'conn_err_sd', 'kBps_avg', 'kBps_sd', 'lmin_avg', 'lmin_sd', 'l99_avg',
    'l99_sd', 'num_samples'))
StartupInfo = namedtuple('StartupInfo', (
    'platform', 'startup_millis_avg', 'startup_millis_sd', 'samples'))
METRICS = (
    'rps', 'l50', 'non2xx', 'pct_err', 'conn_err', 'kBps', 'lmin', 'l99')
DeployCategory = namedtuple('DeployCategory', (
    'platform', 'startup_millis_avg', 'startup_millis_sd', 'samples'))


def get_deployment_category(service, version):
    deployment_id = '-'.join([service, version])
    pieces = deployment_id.split('-')
    if 'cr-managed' in deployment_id:
        platform = 'CR Managed'
        machine_type = 'auto'
        pieces = pieces[2:]
    elif 'highcpu' in deployment_id:
        platform = 'CR GKE'
        machine_type = '-'.join(pieces[1:4])
        pieces = pieces[4:]
    elif 'py27' in deployment_id:
        platform = 'GAE v1'
        assert(pieces[-1] == 'solo')
        assert(pieces[-2].startswith('f'))
        assert(len(pieces[-2]) == 2)
        machine_type = pieces[-2].upper()
        pieces = pieces[1:-2]
    else:
        platform = 'GAE v2'
        machine_type = 'F1'
        pieces = pieces[1:]
    if pieces[-1] == 'solo':
        pieces = pieces[:-2]
    runtime = pieces[0]
    framework = ' '.join(pieces[1:])
    return DeployCategory(platform, machine_type, runtime, framework)


def compute_stats(a):
    if len(a) == 1:
        return Stats(a[0], a[0], 1)
    return Stats(statistics.mean(a),
                 statistics.stdev(a),
                 len(a))


def aggregate_files_and_print(filenames):
    startup_stats, benchmark_stats = aggregate_files(filenames)
    print_startup_stats(startup_stats)
    print('\n')
    print_benchmark_stats(benchmark_stats)


def print_benchmark_stats(benchmark_stats):
    headers = ['Test', 'Platform', 'Machine', 'Runtime', 'Framework']
    for key in METRICS:
        headers.append('%s-avg' % key)
        headers.append('%s-sd' % key)
    headers.append('# Samples')
    print('\t'.join(headers))
    for row in benchmark_stats:
        categories = list(get_deployment_category(row.service, row.version))
        print('\t'.join(str(x)
                        for x in [row.test] + categories + list(row[3:])))


def print_startup_stats(startup_stats):
    print('\t'.join(['Platform', 'Machine', 'Runtime', 'Framework',
                     'Avg Startup Millis', 'StDev SM', '# Samples']))
    for deploy_cat, stats in sorted(
            startup_stats.items(),
            key=lambda item: item[1].startup_millis_avg):
        print('%s\t%s\t%s\t%s\t%d\t%f\t%d' % (
            *deploy_cat, stats.startup_millis_avg,
            stats.startup_millis_sd, len(stats.samples)))


def aggregate_files(filenames):
    raw_startup_stats = defaultdict(list)
    core_stats = defaultdict(dict)
    lines = []
    for fn in filenames:
        with open(fn, 'r') as fin:
            lines.extend(fin.readlines())
    for line in lines:
        if not line:
            continue
        columns = line.split('\t')
        utc_str, service, ver, test, req_per_sec, kBps, lmin, l50 = columns[:8]
        l90, l99, non2xx, secs, pct_err, conn_err, startup_millis = columns[8:]
        if ver == 'n/a':
            # Cloud Run requires a different naming scheme; construct platform,
            # service and version such that the mirror the setup for GAE
            pieces = service.rsplit('-', 3)
            service = '-'.join(['cr', pieces[0]])
            ver = '-'.join(pieces[1:])
        else:
            framework, part2 = ver.split('-', 1)
            service = 'gae-' + service
        if ver.endswith('-' + test):
            ver = ver[:-len(test) - 1]
        elif ver.endswith('-dbjson'):
            ver = ver[:-7]
        # compare ndb tests with the non-ndb version of the test (want to
        # compare them head to head)
        if test.startswith('ndb'):
            test = test[1:]
            if test == 'dbtxtask':
                test = test[2:]
            ver = 'ndb-' + ver
        core_id = Benchmark(service, ver, test)
        my_core_stats = core_stats[core_id]
        my_core_stats.setdefault('rps', []).append(float(req_per_sec))
        my_core_stats.setdefault('kBps', []).append(float(kBps))
        my_core_stats.setdefault('lmin', []).append(float(lmin))
        my_core_stats.setdefault('l50', []).append(float(l50))
        my_core_stats.setdefault('l99', []).append(float(l99))
        my_core_stats.setdefault('non2xx', []).append(int(non2xx))
        my_core_stats.setdefault('pct_err', []).append(float(pct_err))
        my_core_stats.setdefault('conn_err', []).append(int(conn_err))
        deploy_cat = get_deployment_category(service, ver)
        raw_startup_stats[deploy_cat].append(int(startup_millis))

    startup_stats = {}
    for deploy_cat, stats in raw_startup_stats.items():
        if deploy_cat.platform.startswith('CR'):
            # hacky filtering out of junk results from when service must've
            # already been running
            stats = [x for x in stats if x > 2000]
            if not stats:
                continue
        x = compute_stats(stats)
        startup_stats[deploy_cat] = StartupInfo(deploy_cat, x[0], x[1], stats)

    for benchmark, stats in core_stats.items():
        for k in METRICS:
            stats[k] = compute_stats(stats[k])
    benchmark_stats = []
    for benchmark, stats in sorted(core_stats.items(), key=cmp_core):
        values = [benchmark.test, benchmark.service, benchmark.version]
        for k in METRICS:
            values.extend(stats[k][:2])
        values.append(stats['rps'].sz)
        benchmark_stats.append(AggregateResult(*values))
    return startup_stats, benchmark_stats


def cmp_core(item):
    key, val = item
    return (key.test,  # group by test
            val['pct_err'].avg > 0.01,  # high failures last
            -val['rps'].avg)  # highest RPS first


def main(f=aggregate_files_and_print):
    """Aggregate the specified filename."""
    parser = argparse.ArgumentParser()
    parser.add_argument('FILENAME', nargs='*',
                        help='filename(s) to aggregate')
    args = parser.parse_args()
    return f(args.FILENAME)


if __name__ == '__main__':
    main()
