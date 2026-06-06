#! /usr/bin/env python3
"""Compare all kept C++ translator revisions on the full HTG suite.

Companion to 02-htg-search.py, but instead of cpp-vs-py it sweeps the
sequence of kept revisions from the autoresearch speedup loop
(project.REVISIONS: baseline -> ... -> uf-dedup) so the per-revision
translator speedup is visible on the whole hard-to-ground suite.

Because every kept revision is a translator-only optimisation that
produces byte-identical output, we run **translate-only**
(`--translate --translator cpp`) and compare `translator_time_*` /
`translator_peak_memory` directly, rather than paying for an identical
LAMA-first search seven times.

Invoke through `uv run` so the Lab 8 deps resolve:

    uv run --project ../../ ./03-htg-revisions.py --all

Smoke-test locally even on a Slurm login node by forcing local mode:

    AR_FORCE_LOCAL=1 HTG_BENCHMARKS_FLATTENED=/path/to/htg \
        uv run --project ../../ ./03-htg-revisions.py --all
"""
import os

import project

from downward import suites
from downward.experiment import (
    CachedFastDownwardRevision,
    FastDownwardAlgorithm,
    FastDownwardExperiment,
    FastDownwardRun,
)
from lab.experiment import Experiment

from modern_lab_report import ModernAbsoluteReport


REPO = str(project.REPO)
REVISION_CACHE = (
    os.environ.get("DOWNWARD_REVISION_CACHE")
    or project.DIR / "data" / "revision-cache"
)
BUILD_OPTIONS = ["--with-translate-cpp"]
# Translate-only with the C++ backend. H2 invariant synthesis stays on
# (default), matching the cpp-h2 arm of the earlier report.
DRIVER_OPTIONS = [
    "--translate", "--translator", "cpp",
    "--overall-time-limit", "600s",
    "--overall-memory-limit", "8G",
]

FORCE_LOCAL = bool(os.environ.get("AR_FORCE_LOCAL"))

if project.REMOTE and not FORCE_LOCAL:
    BENCHMARKS_DIR = os.environ["HTG_BENCHMARKS_FLATTENED"]
    SUITE = project.SUITE_HTG
    REVISIONS = project.REVISIONS
    ENV = project.TetralithEnvironment(
        extra_options="#SBATCH --account=naiss2025-5-382",
        memory_per_cpu="9G",
        cpus_per_task=1,
    )
else:
    # Local smoke: one alkene instance, only the endpoints (baseline +
    # final) so we build just two revisions.
    BENCHMARKS_DIR = os.environ.get(
        "HTG_BENCHMARKS_FLATTENED",
        str(project.REPO / "misc" / "tests" / "benchmarks" / "autoresearch"))
    SUITE = ["organic-synthesis-alkene:p1.pddl"]
    REVISIONS = [project.REVISIONS[0], project.REVISIONS[-1]]
    ENV = project.LocalEnvironment(processes=2)


# --- Experiment ---------------------------------------------------------------

exp = Experiment(environment=ENV)

# Cache + stage each unique revision's build (mirrors
# FastDownwardExperiment._add_code, generalised to several revisions).
cached_revs = {}
for _nick, rev in REVISIONS:
    if rev in cached_revs:
        continue
    cached = CachedFastDownwardRevision(REVISION_CACHE, REPO, rev, BUILD_OPTIONS)
    cached.cache()
    exp.add_resource("", cached.path, cached.get_relative_exp_path())
    cached_revs[rev] = cached

for nick, rev in REVISIONS:
    algo = FastDownwardAlgorithm(nick, cached_revs[rev], DRIVER_OPTIONS, [])
    for task in suites.build_suite(BENCHMARKS_DIR, SUITE):
        exp.add_run(FastDownwardRun(exp, algo, task))

# Translate-only: exit code + the stock translator parser (the C++ port
# prints the Python phase-log format) capture everything we need.
exp.add_parser(FastDownwardExperiment.EXITCODE_PARSER)
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")


# --- Reports -----------------------------------------------------------------

ATTRIBUTES = [
    "error",
    "translator_time_done",
    "translator_time_parsing",
    "translator_time_normalizing_task",
    "translator_time_generating_datalog_program",
    "translator_time_normalizing_datalog_program",
    "translator_time_computing_model",
    "translator_time_completing_instantiation",
    "translator_time_computing_fact_groups",
    "translator_time_processing_axioms",
    "translator_time_translating_task",
    "translator_time_detecting_unreachable_propositions",
    "translator_time_reordering_and_filtering_variables",
    "translator_time_writing_output",
    "translator_peak_memory",
    "translator_variables", "translator_facts", "translator_mutex_groups",
    "translator_operators", "translator_axioms", "translator_task_size",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", ModernAbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
# Headline: baseline -> final.
add_report(
    "compare-baseline-vs-final",
    cls=project.ComparativeReport,
    algorithm_pairs=[(project.REVISIONS[0][0], project.REVISIONS[-1][0])],
)
# Per-step attribution: each kept revision against its predecessor.
if len(REVISIONS) > 2:
    add_report(
        "compare-consecutive",
        cls=project.ComparativeReport,
        algorithm_pairs=[
            (REVISIONS[i][0], REVISIONS[i + 1][0])
            for i in range(len(REVISIONS) - 1)
        ],
    )

exp.run_steps()
