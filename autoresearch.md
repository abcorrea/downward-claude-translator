# Autoresearch: speed up the C++ translator

## Objective
Make the C++ translator (`src/translate-cpp/`) **as fast as possible** while
producing **byte-for-byte identical** `output.sas` on every benchmark task.
Speed only; correctness is a hard gate, not a trade-off.

## Metric
- **`total_cpu`** (seconds, **lower is better**): sum of the translator's own
  user+system CPU over all tasks in the suite, measured per-process via
  `os.wait4` rusage (build/python/shell overhead excluded).
- Secondary (watch, don't optimize): peak RSS is not currently tracked; add it
  to the runner if an idea trades memory for speed.

## How to run
- Benchmark: `./autoresearch.sh` → prints `METRIC total_cpu=<sec>` x3 (1 warmup
  discarded). Rebuilds the translator first (incremental, ~1-2s, off-metric).
- Correctness: `./autoresearch.checks.sh` → byte-compares every task's
  `output.sas` to its committed reference; non-zero exit on any deviation.
- Decide: `python3 .claude/skills/autoresearch/scripts/decide.py --best "<samples>" --candidate "<samples>" --direction lower`

## The loop
`think -> edit src/translate-cpp -> ./autoresearch.sh -> decide -> if KEEP run
./autoresearch.checks.sh -> commit if checks pass, else revert -> log -> repeat`
Run checks only on benchmark-KEEP candidates (they're off the hot path). A
checks failure reverts exactly like a crash.

## Files in scope (edit these)
- `src/translate-cpp/**` — all translator C++ sources. Hot path for these
  hard-to-ground tasks is grounding: `grounding/{model,build,program,split}.cc`,
  then `instantiate/`, `normalize/`, `parser/`, `simplify/`.

## Off-limits (never edit)
- `misc/tests/run_translator_benchmark.py` (the benchmark harness)
- `misc/tests/benchmarks/autoresearch/**` (the task inputs)
- `misc/tests/benchmarks/autoresearch-refs/**` (the references — the ground
  truth for correctness; only regenerate deliberately if output *intentionally*
  changes, which for a pure speedup it must not)
- `autoresearch.sh`, `autoresearch.checks.sh`

## Constraints
- Output must stay byte-identical to the references (the whole point is a
  faster translator with the *same* result). No algorithmic change that alters
  variable order, mutex groups, operator order, etc.
- C++20; must build with `./build.py release --with-translate-cpp`.
- Keep it simple: removing code while holding the metric is a win; ugly
  complexity for a tiny gain is a discard.
- **Elegant code only, no hacks** (user directive). Every kept change must be a
  clean improvement a maintainer would accept: no benchmark special-casing, no
  fragile micro-hacks, no correctness shortcuts. Prefer better algorithms/data
  structures over tricks. If the only way to win is ugly, discard it.

## Suite (18 tasks, one per domain family, each ~translator_time_done near 20s)
HTG (8): blocksworld-large-simple, childsnack-contents-parsize2-cham7,
genome-edit-distance-positional, logistics-large-simple,
organic-synthesis-original, pipesworld-tankage-nosplit, rovers-large-simple,
visitall-multidimensional-3-dim-visitall-CLOSE-g2.
IPC (10): agricola-sat18-strips, caldera-sat18-adl, flashfill-sat18-adl,
nurikabe-sat18-adl, openstacks-strips, organic-synthesis-split-sat18-strips,
psr-large, satellite, scanalyzer-08-strips, settlers-sat18-adl.
(Families whose slowest task was <=10s were skipped per the selection rule.)

## State
- Ledger: `autoresearch.jsonl` (append-only; config header + one line per run).
- Baseline is the first result line (segment 0).

## Phase profile (baseline, suite-wide CPU, /tmp/profile_phases.py)
- Completing instantiation  36.9% (110.7s)  <- top target (dominant on 10/18 tasks)
- Translating task          18.1% (54.3s)
- Computing model           17.3% (51.9s)   (rovers 19.9s, psr 7.8s)
- Computing fact groups      13.8% (41.5s)   (openstacks 24.0s alone)
- Reordering/filtering        5.3% | Detecting unreachable 4.1% | Axioms 3.3%
- Writing output 1.1%, Parsing 0.2%, Datalog gen/normalize ~0% (already fast)

## What's Been Tried
- Baseline: median 322.97s (samples 326.40/320.72/322.97), HEAD 71fa76e.
- KEEP (89a237c): AtomView allocation-free fact probing in instantiate
  (heterogeneous find, reuse canonical fluent atom). 322.97 -> 289.56s
  (-10.3%, conf 12.9x).
- DISCARD (run 3): raw-id packed join keys in compute_model key_of. Within
  noise (0.89%, conf 0.84x over 6 pooled samples) -- the SSO std::string key
  was already cheap. Lesson: model key_of is not the model-phase bottleneck.
- KEEP (31d9235): reuse thread-local scratch buffer for literal arg
  resolution in instantiate (no per-probe vector alloc). 289.56 -> 280.82s
  (-3.0%, conf 3.5x). Best = 280.82s.
- INSIGHT: openstacks' 24s is entirely the invariant finder (fg.get_groups),
  but that's only ~8% of the suite total, so single-task invariant micro-opts
  won't move the suite metric past the noise floor. Prefer broad phases.
- KEEP (2b03d60): skip per-effect var_mapping copy for parameterless effects
  in instantiate_action. 280.82 -> 268.70s (-4.3%, conf 7.8x). Best = 268.70s.
- Total so far: 322.97 -> 268.70s (-16.8%). All instantiation-phase wins.
- KEEP (e588ed8): reuse thread-local key buffer for atom_key dict lookups in
  Translating-task phase + drop temp positive Atom in negated lookups.
  268.70 -> 265.69s (-1.1%, conf 2.1x, needed 6 pooled samples - marginal).
  Best = 265.69s.
- Re-profile (after exp1/3/4): Instantiation 28% / Computing model 21% (rovers
  21.5s) / Translating task 20% / fact groups 16%. Three phases now close.
- INSIGHT: short SSO strings (model key_of, predicate names) aren't worth
  optimizing (exp2 noise). Wins come from eliminating heap allocs in hot loops
  (long key strings, per-call vectors/maps). Predicate interning likely noise
  too (names are SSO-short).
- DISCARD (run 8): cache predicate hash on Literal for AtomView probe. No
  improvement (median slightly worse) -> predicate hashing is NOT a bottleneck
  (confirms SSO insight). Reverted.
- KEEP-NEUTRAL (48fb50c, run 9): drop redundant double-hash in invariant
  UnionFind::find. Metric-neutral (within noise) but a genuine simplification
  (removed dead work); kept for code quality. Comparison-best stays 259.73s.
  Also signals the invariant solver's per-op micro-structure is NOT openstacks'
  bottleneck (likely the candidate/balance-check COUNT, which is algorithmic
  and would change output if altered -> off limits).

## PLATEAU ANALYSIS (after 9 runs, best 259.73s = -19.6%)
The cheap, output-preserving, low-risk wins are largely captured. Evidence:
3 consecutive non-wins (exp2/exp7 noise, exp8 neutral) across model, instantiate
and invariant phases. Key constraint: output must stay BYTE-IDENTICAL, so only
implementation-efficiency changes are allowed -- NOT algorithmic improvements
(different atom sets / mutex choices would change output). That rules out the
usual big grounding speedups (lifted successor gen, better join ordering,
smarter invariant synthesis). Remaining cost is mostly INTRINSIC:
  - Computing model 21% (rovers 21.5s): semi-naive Datalog join/dedup work;
    per-emitted-atom vector<Arg> + hash-set are inherent. SSO predicate ops
    are cheap (proven). Hard to beat without algorithmic change.
  - Completing instantiation 28%: string-based var_mapping/arg design; the
    remaining cost is string HASHING in resolve_args (var_mapping.find per arg)
    + AtomView hashing. Beating it needs a position-indexed var_mapping
    (resolve literal args to param indices once) -- output-preserving but a
    multi-file refactor of the Condition::instantiate path. = next big swing.
  - Translating task 20%: CondMap std::set<int> + multiply-out map allocs;
    type-coupled to build_sas_operator's unordered_map<int,int>.
NEXT: attempt the position-indexed var_mapping refactor (larger structural
change, output-preserving). If it doesn't clear noise, we're at a sound plateau.
- 
