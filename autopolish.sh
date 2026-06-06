#!/bin/bash
# Runtime GUARD for the autopolish (code-quality) loop. Code quality is the
# objective; runtime is only a guard -- a quality change is rejected only if
# it *significantly* slows the translator down. To keep the loop fast we time
# a representative heavy-task subset (covering the model, instantiation,
# translate and fact-group/invariant phases) rather than all 18 tasks.
#
# Prints one `METRIC total_cpu=<seconds>` per rep (summed translator-only CPU
# over the subset), like autoresearch.sh. Rebuild is off the metric clock.
set -euo pipefail
cd "$(dirname "$0")"

BIN=builds/release/bin/translate-cpp

./build.py release --with-translate-cpp >/tmp/autopolish-build.log 2>&1 || {
    echo "BUILD FAILED -- see /tmp/autopolish-build.log" >&2
    tail -20 /tmp/autopolish-build.log >&2
    exit 1
}
[ -x "$BIN" ] || { echo "translator binary missing after build" >&2; exit 1; }

# Heavy subset, one per dominant phase:
#   rovers/psr -> Computing model; openstacks -> fact groups/invariants;
#   logistics/caldera/nurikabe -> Completing instantiation; blocksworld ->
#   Translating task; visitall -> model.
SUBSET="rovers-large-simple,openstacks-strips,psr-large,blocksworld-large-simple,logistics-large-simple,caldera-sat18-adl,nurikabe-sat18-adl,visitall-multidimensional-3-dim-visitall-CLOSE-g2"

RUNNER=(python3 misc/tests/run_translator_benchmark.py --warmup 1 --reps 3 --tasks "$SUBSET")
if command -v taskset >/dev/null 2>&1; then
    exec taskset -c 1 "${RUNNER[@]}"
else
    exec "${RUNNER[@]}"
fi
