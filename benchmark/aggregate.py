#!/usr/bin/env python3
"""The script aggregates benchmark data."""
import argparse
from collections import defaultdict, namedtuple
import statistics


def main():
    """Aggregate the specified filename."""
    parser = argparse.ArgumentParser()
    parser.add_argument('FILENAME', help='filename to aggregate')
    args = parser.parse_args()
    aggregate_file(args.FILENAME)


Benchmark = namedtuple('Benchmark', ('service', 'version', 'test'))
Stats = namedtuple('Stats', ('avg', 'sdev', 'sz'))


def compute_stats(a):
    return Stats(statistics.mean(a),
                 statistics.stdev(a),
                 len(a))


def aggregate_file(fn):
    startup_stats = defaultdict(list)
    core_stats = defaultdict(dict)
    with open(fn, 'r') as fin:
        lines = fin.read().split('\n')
    for line in lines:
        if not line:
            continue
        columns = line.split('\t')
        utc_str, service, ver, test, req_per_sec, kBps, lmin, l50 = columns[:8]
        l90, l99, non2xx, secs, pct_err, conn_err, startup_millis = columns[8:]
        if ver == 'n/a':
            # Cloud Run requires a different naming scheme; construct platform,
            # service and version such that the mirror the setup for GAE
            pieces = service.rsplit('-', 4)
            platform = 'CR ' + pieces[0]
            service = 'cr-' + pieces[1]
            ver = '-'.join(pieces[2:])
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
        assert ver.endswith('-' + test)
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

    print('\t'.join(['Platform', 'Avg Startup Millis', 'StDev SM', '# Samples']))
    for platform, stats in startup_stats.items():
        startup_stats[platform] = compute_stats(stats)
    for platform, stats in sorted(startup_stats.items(),
                                  key=lambda item: item[1].avg):
        print('%s\t%d\t%f\t%d' % (platform, *stats))

    print('\n')
    headers = ['Test', 'Service', 'Version']
    keys = ['rps', 'l50', 'non2xx', 'pct_err', 'conn_err', 'kBps', 'lmin', 'l99']
    for key in keys:
        headers.append('%s-avg' % key)
        headers.append('%s-sd' % key)
    headers.append('# Samples')
    ignore = set()
    for benchmark, stats in core_stats.items():
        if len(stats['rps']) < 2:
            print('warning: only %d data points for %s %s %s' % (
                len(req_per_sec), *benchmark))
            ignore.add(benchmark)
            continue
        for k in keys:
            stats[k] = compute_stats(stats[k])
    for benchmark in ignore:
        del core_stats[benchmark]
    print('\t'.join(headers))
    for benchmark, stats in sorted(core_stats.items(), key=cmp_core):
        values = [benchmark.test, benchmark.service, benchmark.version]
        for key in keys:
            avg, sd = stats[key][:2]
            values.append(str(avg))
            values.append(str(sd))
        values.append(str(stats['rps'].sz))
        print('\t'.join(values))


def cmp_core(item):
    key, val = item
    return (key.test,  # group by test
            val['pct_err'].avg > 0.01,  # high failures last
            -val['rps'].avg)  # highest RPS first


if __name__ == '__main__':
    main()
