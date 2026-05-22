"""Shared helpers for the translator-port experiment series.

Modelled after Scorpion's `experiments/.../project.py` pattern (see
https://github.com/jendrikseipp/scorpion/tree/scorpion/experiments) but
scoped to this repo: we only ship Lab integration for the bundled
`misc/tests/benchmarks/` suite and the two translator front-ends (the
C++ port at `src/translate-cpp/build/translate` and the Python
translator at `src/translate`).

Heavier helpers (Slurm environments, scatter plots, latex reports) can
be lifted from Scorpion's project.py once we move beyond the local
suite; keep this file small until then.
"""
from __future__ import annotations

# Compatibility shim for `downward.reports` on Python >= 3.10:
# lab 4.2's report base imports `collections.Iterable`, removed in 3.10.
import collections
import collections.abc
if not hasattr(collections, "Iterable"):
    collections.Iterable = collections.abc.Iterable  # type: ignore[attr-defined]

import os
from pathlib import Path

from downward.experiment import FastDownwardExperiment
from downward.reports.absolute import AbsoluteReport  # noqa: F401  (re-export)
from lab.environments import LocalEnvironment  # noqa: F401  (re-export)
from lab.experiment import ARGPARSER  # noqa: F401  (re-export)
from lab.reports import Attribute, geometric_mean


# Project layout.
DIR = Path(__file__).resolve().parent
REPO = DIR.parent.parent          # downward-new-translator/
BENCHMARKS_DIR = REPO / "misc" / "tests" / "benchmarks"
FAST_DOWNWARD = REPO / "fast-downward.py"
CPP_TRANSLATE = REPO / "src" / "translate-cpp" / "build" / "translate"

# The 10 instances currently bundled (kept here so any new instance the
# user adds shows up automatically via the directory listing below).
LOCAL_SUITE = sorted(
    f"{d.name}:{p.name}"
    for d in BENCHMARKS_DIR.iterdir() if d.is_dir()
    for p in d.iterdir()
    if p.suffix == ".pddl" and "domain" not in p.name
)

# Lab-recognised translator stats are emitted by both translators
# (Python emits them directly, my C++ port emits the same `Translator
# variables: N` etc.). These attributes line up with what the bundled
# downward.scripts.translator_parser sets.
TRANSLATOR_ATTRIBUTES = [
    Attribute("translator_time_done", functions=geometric_mean, digits=2),
    "translator_variables",
    "translator_derived_variables",
    "translator_facts",
    "translator_goal_facts",
    "translator_mutex_groups",
    "translator_total_mutex_groups_size",
    "translator_operators",
    "translator_axioms",
    "translator_task_size",
    "translator_peak_memory",
]


def assert_paths_exist():
    """Fail fast if something the experiment needs is missing."""
    missing = [
        str(p) for p in (BENCHMARKS_DIR, FAST_DOWNWARD)
        if not p.exists()
    ]
    if missing:
        raise SystemExit(
            "Missing required paths:\n  " + "\n  ".join(missing) +
            "\nRun `cmake --build src/translate-cpp/build -j` and "
            "ensure misc/tests/benchmarks/ is populated.")
    if not CPP_TRANSLATE.exists():
        raise SystemExit(
            f"C++ translator binary not found at {CPP_TRANSLATE}.\n"
            "Build with: cmake -S src/translate-cpp -B src/translate-cpp/build "
            "-DCMAKE_BUILD_TYPE=Release && cmake --build "
            "src/translate-cpp/build -j")


# Convenience: which translator implementation a run should use.
# We pass these through Lab's per-run env so fast-downward.py's driver
# picks the right binary (see driver/run_components.py).
TRANSLATOR_ENV = {
    "cpp": {"FD_TRANSLATE_CPP": str(CPP_TRANSLATE)},
    "py":  {"FD_TRANSLATE_PY": "1"},
}


def benchmarks_env():
    """Lab's `suites.build_suite` needs DOWNWARD_BENCHMARKS to resolve
    relative-suite descriptors; some downstream tools also read it."""
    return {"DOWNWARD_BENCHMARKS": str(BENCHMARKS_DIR)}
