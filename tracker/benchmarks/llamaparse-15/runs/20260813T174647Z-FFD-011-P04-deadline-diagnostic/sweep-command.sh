#!/usr/bin/env bash
set -euo pipefail

for diagnostic_budget in 5 10 15 30
do
  case "$diagnostic_budget" in
    5) budget_dir=budget-005 ;;
    10) budget_dir=budget-010 ;;
    15) budget_dir=budget-015 ;;
    30) budget_dir=budget-030 ;;
  esac
  for diagnostic_case in clinical-study ny-timetable
  do
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
      -m tests.benchmarks.p04_deadline_diagnostic \
      --case "$diagnostic_case" \
      --budget-seconds "$diagnostic_budget" \
      --output-dir \
      "tracker/benchmarks/llamaparse-15/runs/20260813T174647Z-FFD-011-P04-deadline-diagnostic/sweep/$budget_dir/$diagnostic_case"
  done
done
