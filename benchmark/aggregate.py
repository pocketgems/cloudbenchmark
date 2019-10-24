#!/usr/bin/env python3
"""The script aggregates benchmark data."""
import argparse
from collections import defaultdict, namedtuple
import statistics


def main():
    """Aggregate the specified filename."""
    parser = argparse.ArgumentParser()
    parser.add_argument('FILENAME', nargs='*',
                        help='filename(s) to aggregate')
    args = parser.parse_args()
    aggregate_files_and_print(args.FILENAME)


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


def compute_stats(a):
    return Stats(statistics.mean(a),
                 statistics.stdev(a),
                 len(a))


def aggregate_files_and_print(filenames):
    startup_stats, benchmark_stats = aggregate_files(filenames)
    print('\t'.join(['Platform', 'Avg Startup Millis', 'StDev SM', '# Samples']))
    for platform, stats in sorted(startup_stats.items(),
                                  key=lambda item: item[1].startup_millis_avg):
        print('%s\t%d\t%f\t%d' % (platform, stats.startup_millis_avg,
                                  stats.startup_millis_sd,
                                  len(stats.samples)))
    print('\n')
    headers = ['Test', 'Service', 'Version']
    for key in METRICS:
        headers.append('%s-avg' % key)
        headers.append('%s-sd' % key)
    headers.append('# Samples')
    print('\t'.join(headers))
    for row in benchmark_stats:
        print('\t'.join(str(x) for x in row))


def aggregate_files(filenames):
    startup_stats = defaultdict(list)
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
            platform = 'CR ' + pieces[0]
            service = '-'.join(['cr', pieces[0]])
            ver = '-'.join(pieces[1:])
        else:
            framework, part2 = ver.split('-', 1)
            platform = service + '-' + part2.rsplit('-', 1)[0]
            service = 'gae-' + service
        startup_stats[platform].append(int(startup_millis))
        # compare ndb tests with the non-ndb version of the test (want to
        # compare them head to head)
        if test.startswith('ndb'):
            test = test[1:]
            if test == 'dbtxtask':
                test = test[2:]
            ver = 'ndb-' + ver
        ver = ver[:-len(test) - 1]
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

    for platform, stats in startup_stats.items():
        x = compute_stats(stats)
        startup_stats[platform] = StartupInfo(platform, x[0], x[1], stats)

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


if __name__ == '__main__':
    main()
