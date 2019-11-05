#!/usr/bin/env python3
"""The script evaluates aggregate benchmark data."""
import argparse
from collections import defaultdict, namedtuple

import aggregate


def get_primary_metric(test):
    return 'rps_avg'


def create_matrix(rows):
    # for each test, calculate the best performer
    bests_by_test = {}  # test name --> best result
    for row in rows:
        if row.pct_err_avg < 0.01:
            score = getattr(row, get_primary_metric(row.test))
        else:
            score = 0  # high error rates don't qualify for best
        if row.test not in bests_by_test or score > bests_by_test[row.test]:
            bests_by_test[row.test] = score

    # for every deployment x test, calculate % of best
    deployments = {}  # deployment -> (test -> % of best)
    for row in rows:
        x = deployments.setdefault((row.service, row.version), {})
        metric = get_primary_metric(row.test)
        x[row.test] = getattr(row, metric) / (1 or bests_by_test[row.test])

    # for every deployment, calculate overall % of best (across all tests)
    for x in deployments.values():
        x['overall'] = sum(x.values()) / len(x)
    return bests_by_test, deployments


def print_matrix(bests_by_test, deployments):
    tests = list(bests_by_test.keys())
    tests.sort()
    headers = ['Platform', 'Machine', 'Runtime', 'Framework']
    headers.extend(tests)
    headers.append('Avg % of Best')
    print('\t'.join(headers))
    deployments = sorted(deployments.items(),
                         key=lambda x: -x[1]['overall'])
    row = ['', '', '', 'BEST (requests per second)']
    for test in tests:
        val = bests_by_test[test]
        if val >= 100:
            row.append('%d' % val)
        else:
            row.append('%.1f' % val)
    row.append('--')
    print('\t'.join(row))
    for deployment_id, results in deployments:
        row = list(aggregate.get_deployment_category(*deployment_id))
        for test in tests + ['overall']:
            row.append(str(results.get(test, '')))
        print('\t'.join(row))


def main():
    """Compute overall results the specified filename(s)."""
    startup_stats, benchmark_stats = aggregate.main(aggregate.aggregate_files)
    aggregate.print_startup_stats(startup_stats)
    print('\n')
    print_matrix(*create_matrix(benchmark_stats))
    print('\n')
    aggregate.print_benchmark_stats(benchmark_stats)


if __name__ == '__main__':
    main()
