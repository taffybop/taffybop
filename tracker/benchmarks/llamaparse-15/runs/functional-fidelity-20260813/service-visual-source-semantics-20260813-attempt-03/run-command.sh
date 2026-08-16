#!/usr/bin/env bash
set -euo pipefail

workspace="/Users/vignesh/Downloads/taffybop"
prior="$workspace/tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/service-visual-source-semantics-20260813-attempt-02/run-command.sh"

# Reuse the reviewed release-profile command byte-for-byte except for the new
# immutable output root. The prior HTTP/DOM artifacts remain untouched.
sed \
  's/service-visual-source-semantics-20260813-attempt-02/service-visual-source-semantics-20260813-attempt-03/g' \
  "$prior" | /bin/bash
