#!/usr/bin/env python3
"""Flake-rate reporter for tests tagged @pytest.mark.xfail_flaky.

Usage:
	python scripts/flake_check.py [--count N] [--root PATH]

Outcomes per test:
	true-race    0 < pass% < 100  — keep, investigate
	stable-xfail 0% pass          — delete (never passes)
	false-flake  100% pass        — remove xfail_flaky marker
"""

import argparse
import subprocess
import sys
from pathlib import Path


RUNS_DEFAULT = 20


def collect_tests(root: Path) -> list[str]:
	result = subprocess.run(
		[
			sys.executable, "-m", "pytest",
			"--collect-only", "-m", "xfail_flaky", "-q",
			"--no-header",
		],
		cwd=root,
		capture_output=True,
		text=True,
	)
	tests = []
	for line in result.stdout.splitlines():
		line = line.strip()
		if "::" in line and not line.startswith("no tests"):
			tests.append(line)
	return tests


def run_once(test_id: str, root: Path) -> bool:
	result = subprocess.run(
		[
			sys.executable, "-m", "pytest",
			test_id,
			"-x", "--tb=no", "-q", "--no-header",
			"-p", "no:randomly",  # keep order deterministic
		],
		cwd=root,
		capture_output=True,
		text=True,
	)
	return result.returncode == 0


def check_test(test_id: str, count: int, root: Path) -> tuple[int, int]:
	"""Returns (passes, total)."""
	passes = 0
	for _ in range(count):
		if run_once(test_id, root):
			passes += 1
	return passes, count


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--count", type=int, default=RUNS_DEFAULT,
		help=f"Runs per test (default {RUNS_DEFAULT})")
	parser.add_argument("--root", type=Path, default=Path("."),
		help="Project root (default: cwd)")
	args = parser.parse_args()

	root = args.root.resolve()
	count = args.count

	print(f"Collecting xfail_flaky tests from {root}…")
	tests = collect_tests(root)

	if not tests:
		print("No tests tagged xfail_flaky found.")
		return

	print(f"Found {len(tests)} test(s). Running each {count}×.\n")

	true_races: list[tuple[str, int, int]] = []
	stable_xfails: list[str] = []
	false_flakes: list[str] = []

	for test_id in tests:
		print(f"  {test_id} … ", end="", flush=True)
		passes, total = check_test(test_id, count, root)
		rate = passes / total
		label = f"{passes}/{total} ({rate:.0%})"
		print(label)

		if passes == 0:
			stable_xfails.append(test_id)
		elif passes == total:
			false_flakes.append(test_id)
		else:
			true_races.append((test_id, passes, total))

	print()
	if true_races:
		print("TRUE RACES  (intermittent — investigate):")
		for tid, p, t in true_races:
			print(f"  {p}/{t} ({p/t:.0%})  {tid}")
		print()

	if stable_xfails:
		print("STABLE XFAILS  (0% pass — consider deleting):")
		for tid in stable_xfails:
			print(f"  {tid}")
		print()

	if false_flakes:
		print("FALSE FLAKES  (100% pass — remove xfail_flaky marker):")
		for tid in false_flakes:
			print(f"  {tid}")
		print()

	if not true_races and not stable_xfails and not false_flakes:
		print("Nothing to triage.")


if __name__ == "__main__":
	main()
