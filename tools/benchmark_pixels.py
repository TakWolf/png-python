"""Repeatable in-memory PNG timing; run with `python -m tools.benchmark_pixels`."""

import argparse
import json
import platform
from random import Random
from statistics import median
from time import perf_counter

from png import PngFilterType, PngHeader, PngImage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--size', type=int, default=12)
    parser.add_argument('--pattern', choices=('gradient', 'solid', 'noise'), default='gradient')
    parser.add_argument('--iterations', type=int, default=100)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if min(args.size, args.iterations, args.repeats) < 1:
        parser.error('size, iterations and repeats must be positive')
    if args.pattern == 'solid':
        bitmap = [[255, 0, 0, 255] * args.size for _ in range(args.size)]
    elif args.pattern == 'noise':
        random = Random(0)
        bitmap = [[random.randrange(256) for _ in range(args.size * 4)] for _ in range(args.size)]
    else:
        bitmap = [
            [sample for x in range(args.size) for sample in ((x * 17) % 256, (y * 31) % 256, (x ^ y) % 256, 255)]
            for y in range(args.size)
        ]
    image = PngImage(PngHeader((args.size, args.size)), bitmap)
    encoded = image.dump_to_bytes(filter_type=PngFilterType.NONE)
    jobs = {
        'parse': lambda: PngImage.parse(encoded),
        'dump_none': lambda: image.dump_to_bytes(filter_type=PngFilterType.NONE),
        'dump_adaptive': image.dump_to_bytes,
    }
    timings = {}
    for name, operation in jobs.items():
        operation()  # Warm up outside the measured repetitions.
        runs = []
        for _ in range(args.repeats):
            start = perf_counter()
            for _ in range(args.iterations):
                operation()
            runs.append((perf_counter() - start) * 1000 / args.iterations)
        timings[name] = median(runs)
    print(
        json.dumps(
            {
                'python': platform.python_version(),
                'size': args.size,
                'pattern': args.pattern,
                'iterations': args.iterations,
                'repeats': args.repeats,
                'median_ms_per_image': timings,
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
