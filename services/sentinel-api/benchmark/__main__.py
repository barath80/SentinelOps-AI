"""Run the benchmark: python -m benchmark --seeds 20 --out ../../docs/benchmark-results.md"""
import argparse
from pathlib import Path

from .report import render
from .runner import run_benchmark, write_json


def main() -> None:
    ap = argparse.ArgumentParser(description="SentinelOps reliability benchmark")
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--systems", nargs="*", help="subset of systems")
    ap.add_argument("--scenarios", nargs="*", help="subset of scenario ids")
    ap.add_argument("--out", help="write a markdown report here")
    ap.add_argument("--json", help="write raw per-run results here")
    args = ap.parse_args()
    result = run_benchmark(args.seeds, args.systems, args.scenarios)
    if args.json:
        write_json(result, args.json)
    text = render(result)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
