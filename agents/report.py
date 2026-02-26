#!/usr/bin/env python3
"""Telemetry report for a Keywork agent goal.

Reads agents/goals/{name}/telemetry.jsonl and prints a summary of cost,
duration, token usage, and phase breakdown.

Usage: python3 agents/report.py <goal-name>
"""
import json
import sys
from collections import defaultdict
from pathlib import Path


def load_telemetry(goal_name):
    telemetry_file = Path(f"agents/goals/{goal_name}/telemetry.jsonl")
    if not telemetry_file.exists():
        # Also check _completed
        telemetry_file = Path(f"agents/goals/_completed/{goal_name}/telemetry.jsonl")
    if not telemetry_file.exists():
        print(f"No telemetry file found for goal '{goal_name}'", file=sys.stderr)
        sys.exit(1)

    records = []
    with telemetry_file.open() as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Warning: skipping malformed line {line_num}: {e}", file=sys.stderr)

    return records


def fmt_duration(ms):
    if ms is None or ms == 0:
        return "—"
    if ms < 60_000:
        return f"{ms / 1000:.0f}s"
    return f"{ms / 60_000:.1f}m"


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def print_summary(records, goal_name):
    total_cost = sum(r.get("total_cost_usd", 0) for r in records)
    total_duration = sum(r.get("duration_ms", 0) for r in records)
    total_turns = sum(r.get("num_turns", 0) for r in records)
    errors = sum(1 for r in records if r.get("is_error"))
    repos = set(r.get("repo", "unknown") for r in records)

    print(f"\n{'=' * 70}")
    print(f"  Telemetry Report: {goal_name}")
    print(f"{'=' * 70}")
    print(f"  Agent runs:   {len(records)}")
    print(f"  Repo:         {', '.join(repos)}")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Duration:     {fmt_duration(total_duration)}")
    print(f"  Total turns:  {total_turns}")
    if errors:
        print(f"  Errors:       {errors}")
    print()


def print_by_phase(records):
    by_phase = defaultdict(lambda: {"count": 0, "cost": 0.0, "duration": 0, "turns": 0})

    for r in records:
        phase = r.get("phase", "unknown")
        by_phase[phase]["count"] += 1
        by_phase[phase]["cost"] += r.get("total_cost_usd", 0)
        by_phase[phase]["duration"] += r.get("duration_ms", 0)
        by_phase[phase]["turns"] += r.get("num_turns", 0)

    print(f"  {'Phase':<12} {'Runs':>5} {'Cost':>10} {'Avg Time':>10} {'Avg Turns':>10}")
    print(f"  {'-' * 12} {'-' * 5} {'-' * 10} {'-' * 10} {'-' * 10}")

    for phase in ["plan", "build", "final_gate", "gate", "promote"]:
        if phase not in by_phase:
            continue
        s = by_phase[phase]
        avg_dur = s["duration"] / s["count"] if s["count"] else 0
        avg_turns = s["turns"] / s["count"] if s["count"] else 0
        print(
            f"  {phase:<12} {s['count']:>5} "
            f"${s['cost']:>9.4f} "
            f"{fmt_duration(avg_dur):>10} "
            f"{avg_turns:>10.1f}"
        )

    # Any non-standard phases
    for phase in sorted(by_phase):
        if phase in ("plan", "build", "final_gate", "gate", "promote"):
            continue
        s = by_phase[phase]
        avg_dur = s["duration"] / s["count"] if s["count"] else 0
        avg_turns = s["turns"] / s["count"] if s["count"] else 0
        print(
            f"  {phase:<12} {s['count']:>5} "
            f"${s['cost']:>9.4f} "
            f"{fmt_duration(avg_dur):>10} "
            f"{avg_turns:>10.1f}"
        )
    print()


def print_by_model(records):
    by_model = defaultdict(lambda: {"input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "cost": 0.0})

    for r in records:
        for model, usage in (r.get("model_usage") or {}).items():
            by_model[model]["input"] += usage.get("inputTokens", 0)
            by_model[model]["output"] += usage.get("outputTokens", 0)
            by_model[model]["cache_read"] += usage.get("cacheReadInputTokens", 0)
            by_model[model]["cache_create"] += usage.get("cacheCreationInputTokens", 0)
            by_model[model]["cost"] += usage.get("costUSD", 0)

    if not by_model:
        return

    print(f"  {'Model':<35} {'Input':>8} {'Output':>8} {'Cache R':>8} {'Cost':>10}")
    print(f"  {'-' * 35} {'-' * 8} {'-' * 8} {'-' * 8} {'-' * 10}")

    for model in sorted(by_model):
        s = by_model[model]
        print(
            f"  {model:<35} "
            f"{fmt_tokens(s['input']):>8} "
            f"{fmt_tokens(s['output']):>8} "
            f"{fmt_tokens(s['cache_read']):>8} "
            f"${s['cost']:>9.4f}"
        )
    print()


def print_timeline(records):
    print(f"  {'#':>3} {'Phase':<12} {'Cost':>9} {'Time':>8} {'Turns':>6}")
    print(f"  {'-' * 3} {'-' * 12} {'-' * 9} {'-' * 8} {'-' * 6}")

    for i, r in enumerate(records, 1):
        phase = r.get("phase", "?")
        cost = r.get("total_cost_usd", 0)
        duration = fmt_duration(r.get("duration_ms", 0))
        turns = r.get("num_turns", 0)
        error = " ERR" if r.get("is_error") else ""
        print(f"  {i:>3} {phase:<12} ${cost:>8.4f} {duration:>8} {turns:>6}{error}")
    print()


def print_insights(records):
    build_count = sum(1 for r in records if r.get("phase") == "build")
    plan_count = sum(1 for r in records if r.get("phase") == "plan")

    if plan_count == 0:
        return

    ratio = build_count / plan_count
    print(f"  Build-to-plan ratio: {ratio:.1f}:1", end="")
    if ratio < 3:
        print("  (frequent replanning — blockers or discoveries?)")
    elif ratio > 8:
        print("  (long build runs between replans)")
    else:
        print()

    # Flag outlier builds (>2x average duration)
    build_durations = [r.get("duration_ms", 0) for r in records if r.get("phase") == "build"]
    if len(build_durations) >= 3:
        avg = sum(build_durations) / len(build_durations)
        outliers = [(i, d) for i, d in enumerate(build_durations, 1) if d > avg * 2]
        if outliers:
            print(f"  Slow builds (>2x avg): {', '.join(f'build #{n} ({fmt_duration(d)})' for n, d in outliers)}")
    print()


def main():
    if len(sys.argv) != 2:
        print("Usage: python3 agents/report.py <goal-name>", file=sys.stderr)
        sys.exit(1)

    goal_name = sys.argv[1]
    records = load_telemetry(goal_name)

    if not records:
        print(f"No telemetry records found for goal '{goal_name}'.")
        sys.exit(0)

    print_summary(records, goal_name)
    print_by_phase(records)
    print_by_model(records)
    print_timeline(records)
    print_insights(records)


if __name__ == "__main__":
    main()
