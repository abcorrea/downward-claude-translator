# Autopolish: improve C++ translator code quality

## Objective
Make `src/translate-cpp/` **more readable, more idiomatic, and more modern
(C++20)** without changing behaviour and without significantly slowing it
down. Quality is the goal; runtime is only a guard.

## Acceptance (a change is KEPT iff all hold)
1. **Genuine quality win** (agent judgment): improves readability, uses a
   clearer/safer C++ idiom, or adopts a C++20 feature that makes the code
   simpler. Pure churn or "different but not better" is rejected.
2. **Behaviour preserved**: `./autoresearch.checks.sh` passes — every task's
   output is byte-identical (or, failing that, canonically equivalent) to its
   reference. A mismatch reverts like a crash.
3. **No significant slowdown**: `./autopolish.sh` (heavy-task subset, 3 reps)
   median is not more than ~5% slower than the autopolish baseline, judged
   with scripts/decide.py. Small regressions/improvements are fine.

## How to run
- Quality changes: edit `src/translate-cpp/**`.
- Runtime guard: `./autopolish.sh` -> `METRIC total_cpu=<sec>` x3 (subset).
- Correctness: `./autoresearch.checks.sh` (all 18 tasks, byte/canonical).
- Decide (guard): `python3 ~/.claude/skills/autoresearch/scripts/decide.py
  --best "<baseline subset samples>" --candidate "<new>" --direction lower`.
  REJECT only if the candidate is *significantly slower*: improvement_rel
  < -0.05 (>5% slower) AND confidence >= 2. Otherwise the guard passes.
  Compare against the FIXED autopolish baseline (don't ratchet) so cumulative
  runtime stays within ~5% of baseline.

## The loop
`pick a quality improvement -> edit -> ./autoresearch.checks.sh -> (if the
change could affect runtime) ./autopolish.sh + guard -> keep or revert ->
log -> repeat`. Cosmetic-only changes (renames, comments, const, formatting)
are runtime-neutral by construction: run only the correctness check and skip
the runtime guard.

## Files in scope
- `src/translate-cpp/**` — all translator C++ sources/headers.

## Off-limits (never edit)
- `misc/tests/run_translator_benchmark.py`, `misc/tests/benchmarks/**`,
  `misc/tests/benchmarks/autoresearch-refs/**`, `autoresearch.sh`,
  `autoresearch.checks.sh`, `autopolish.sh`.

## Constraints
- C++20; must build with `./build.py release --with-translate-cpp`.
- Behaviour identical (byte/canonical to reference).
- Don't sacrifice clarity for speed or vice versa; reject changes that are
  uglier, and reject quality changes that are >5% slower.

## State
- Ledger: `autoresearch.jsonl`, new segment (config header `autopolish`).
  Guard metric = total_cpu on the heavy subset (lower better, used as a guard).
- Branch: `autopolish` (from autoresearch revision 8747edd / translator 48fb50c).

## Idea backlog (C++20 / idioms / readability)
- `x.find(k) != x.end()` / `x.count(k)` -> `x.contains(k)` (C++20). Broad,
  runtime-neutral readability win.
- range-based for / `<ranges>` algorithms (std::ranges::any_of/find/sort)
  instead of manual index loops where it reads better.
- structured bindings; `auto` where it aids readability.
- `[[maybe_unused]]` instead of `(void)x`.
- `std::string_view` params for read-only string args.
- `using enum` for enum-heavy switch/visit sites.
- `std::erase_if` (C++20) instead of remove-erase idiom.
- replace bare `std::function` hot callbacks ONLY if it also reads better
  (and guard runtime).

## What's Been Tried
- Baseline (segment 1): subset guard median 166.6s (translator code 48fb50c).
- KEEP c2e3f68: C++20 .contains() for .count() membership checks (11 files;
  not timer chrono). Byte-identical; guard neutral.
- KEEP 71cc14c: C++20 .contains() for find()!=end()/==end() membership
  (iterator-binding find()s left alone). Byte-identical; guard neutral.
- KEEP 2126410: std::erase_if + [[maybe_unused]] (C++20). Byte-identical.
- KEEP 15b29ff: 43x std::ranges algorithms (sort/find/any_of/...). Byte-
  identical; guard neutral. NOTE: std::ranges::sort needs std::totally_ordered
  elements; vector<Atom>/vector<InvariantPart> define only operator< so those
  5 sorts stay std::sort.
- INSIGHT: the C++20 .contains()/ranges idioms are byte-identical and guard-
  neutral (libstdc++ ranges::sort == std::sort introsort, same tie-breaking).
- KEEP bad2a75: std::iota for two sequential 0..n fills. Byte-identical.

## CONVERGENCE (after 5 quality keeps)
Broad, high-value C++20/idiom modernizations are captured: .contains() (count
+ find!=end), std::ranges algorithms (x43), std::erase_if, [[maybe_unused]],
std::iota. A scan found the codebase already modern otherwise: no typedef
(all `using`), no plain enum (all `enum class`), no NULL, no C-style casts;
structured bindings/auto already pervasive. All 5 keeps byte-identical and
runtime-guard-neutral (slightly faster, ~163-164s vs 166.6s subset).
Remaining candidates are sparse/judgment-heavy and were deliberately NOT done:
- range-based for: most index loops genuinely need the index (parallel arrays
  args[i]/other.args[i], triangular i<j, or i-as-value idx[name]=i). Safe
  pure-subscript loops are rare.
- std::endl -> '\n': left as-is; the flush is load-bearing for log visibility
  under the SIGXCPU timeout handler.
- using enum / std::string_view params: subjective / lifetime-risky; skipped.
NEXT (if resumed): selective per-loop range-for on confirmed pure-subscript
sites; or deeper structural readability (extract helpers) with guard.
-
