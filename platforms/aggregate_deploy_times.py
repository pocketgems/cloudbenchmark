#!/usr/bin/env python3
"""The script aggregates deployment times."""
import argparse
from collections import defaultdict, namedtuple
import statistics


def main():
    """Aggregate the specified filename."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--filename', help='filename to aggregate',
                        default='deploy_log.tsv')
    args = parser.parse_args()
    aggregate_file(args.filename)


def aggregate_file(fn):
    stats = defaultdict(list)
    with open(fn, 'r') as fin:
        lines = fin.read().split('\n')
    for line in lines:
        if not line:
            continue
        service, secs = line.split('\t')[:2]
        secs = float(secs)
        stats[service].append(secs)
    output = {}
    for service, secs_arr in stats.items():
        output[service] = (statistics.mean(secs_arr),
                           statistics.stdev(secs_arr),
                           min(secs_arr),
                           len(secs_arr))
    print('\t'.join([
        'Deploy Category', 'Avg Deploy Secs', 'StDev', 'Min', '# Samples']))
    for service, (avg, sdev, minv, n) in sorted(output.items(),
                                                key=lambda item: item[1][0]):
        print ('%s\t%.1f\t%.1f\t%.1f\t%d' % (service, avg, sdev, minv, n))


if __name__ == '__main__':
    main()
