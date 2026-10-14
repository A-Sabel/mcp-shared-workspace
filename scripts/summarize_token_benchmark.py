"""Compare paired baseline/candidate model usage from a benchmark CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def _integer(row: dict[str, str], field: str) -> int | None:
    value = (row.get(field) or "").strip()
    if not value:
        return None
    number = int(value)
    if number < 0:
        raise ValueError(f"{field} cannot be negative.")
    return number


def _flag(row: dict[str, str], field: str) -> bool | None:
    value = (row.get(field) or "").strip().lower()
    if not value:
        return None
    if value in {"1", "yes", "y", "true", "pass"}:
        return True
    if value in {"0", "no", "n", "false", "fail"}:
        return False
    raise ValueError(f"{field} must be blank or yes/no (1/0).")


def summarize(csv_path: Path) -> dict[str, int | float | None]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    baseline_tokens = candidate_tokens = paired = 0
    baseline_pass = baseline_complete = candidate_pass = candidate_complete = 0
    evaluated = 0
    for row in rows:
        bi, bo = _integer(row, "baseline_input_tokens"), _integer(row, "baseline_output_tokens")
        ci, co = _integer(row, "candidate_input_tokens"), _integer(row, "candidate_output_tokens")
        if None not in (bi, bo, ci, co):
            baseline_tokens += bi + bo
            candidate_tokens += ci + co
            paired += 1
            bp, bc = _flag(row, "baseline_pass"), _flag(row, "baseline_complete")
            cp, cc = _flag(row, "candidate_pass"), _flag(row, "candidate_complete")
            if None not in (bp, bc, cp, cc):
                evaluated += 1
                baseline_pass += bp
                baseline_complete += bc
                candidate_pass += cp
                candidate_complete += cc
    savings = (
        (baseline_tokens - candidate_tokens) * 100 / baseline_tokens
        if baseline_tokens
        else None
    )
    return {
        "paired_tasks": paired,
        "evaluated_tasks": evaluated,
        "baseline_tokens": baseline_tokens,
        "candidate_tokens": candidate_tokens,
        "token_savings_percent": savings,
        "baseline_passed": baseline_pass,
        "candidate_passed": candidate_pass,
        "baseline_complete": baseline_complete,
        "candidate_complete": candidate_complete,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", type=Path, help="Benchmark results CSV.")
    args = parser.parse_args()
    report = summarize(args.csv_file)
    print(f"Paired tasks with token counts: {report['paired_tasks']}")
    print(f"Tasks with quality and coverage ratings: {report['evaluated_tasks']}")
    print(f"Baseline tokens:  {report['baseline_tokens']}")
    print(f"Candidate tokens: {report['candidate_tokens']}")
    savings = report["token_savings_percent"]
    print(f"Token change:     {'n/a' if savings is None else f'{savings:.1f}% saved'}")
    print(
        f"Pass: {report['baseline_passed']} -> {report['candidate_passed']}  |  "
        f"Complete: {report['baseline_complete']} -> {report['candidate_complete']}"
    )
    print("Token change is meaningful only alongside pass rate and completeness.")


if __name__ == "__main__":
    main()
