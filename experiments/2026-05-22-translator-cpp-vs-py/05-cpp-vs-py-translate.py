#! /usr/bin/env python3
"""C++ vs Python translator on the full benchmark suite (translate-only).

Confirms the new C++ translator (src/translate-cpp/) behaves identically to
the old Python translator (src/translate/) on all downward-benchmarks, and
measures their translation times. Both algorithms run the SAME pinned
revision and differ only in `--translator {py,cpp}`; we run translate-only
(`--translate`) since we care about translation, not search.

Equivalence is checked via the translator output statistics
(translator_variables / facts / operators / mutex_groups / axioms /
task_size): if these match per task, the produced SAS+ tasks are equivalent
(up to variable/operator ordering). Per the repo README the only expected
deviations are instances where Python's own H2 invariant-synthesis RNG picks
a different (equally valid) mutex grouping.

Reports include a RELATIVE scatter plot of translator_time_done (py vs cpp).

    uv run --project ../../ ./05-cpp-vs-py-translate.py --all

Local smoke (even on a Slurm login node):

    AR_FORCE_LOCAL=1 uv run --project ../../ ./05-cpp-vs-py-translate.py --all
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
from downward.reports.scatter import ScatterPlotReport
from lab.experiment import Experiment

from modern_lab_report import ModernAbsoluteReport


REPO = str(project.REPO)
REVISION_CACHE = (
    os.environ.get("DOWNWARD_REVISION_CACHE")
    or project.DIR / "data" / "revision-cache"
)
# Pinned to the autopolish HEAD (improved C++ translator). The Python
# translator in this revision is upstream/unchanged.
REV = "1c949de"  # autopolish HEAD with Part A (includes + alloc-free operator<)
BUILD_OPTIONS = ["--with-translate-cpp"]
# Translate-only; H2 invariant synthesis on (default), matching normal use.
DRIVER_COMMON = ["--translate", "--overall-time-limit", "600s",
                 "--overall-memory-limit", "8G"]
TRANSLATORS = [("py", ["--translator", "py"]), ("cpp", ["--translator", "cpp"])]

FORCE_LOCAL = bool(os.environ.get("AR_FORCE_LOCAL"))

if project.REMOTE and not FORCE_LOCAL:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = project.SUITE_SATISFICING
    ENV = project.TetralithEnvironment(
        extra_options="#SBATCH --account=naiss2025-5-382",
        memory_per_cpu="9G",
        cpus_per_task=1,
    )
else:
    BENCHMARKS_DIR = str(project.LOCAL_BENCHMARKS_DIR)
    SUITE = ["gripper:prob01.pddl", "miconic:s1-0.pddl"]
    ENV = project.LocalEnvironment(processes=2)


exp = Experiment(environment=ENV)

cached_rev = CachedFastDownwardRevision(REVISION_CACHE, REPO, REV, BUILD_OPTIONS)
cached_rev.cache()
exp.add_resource("", cached_rev.path, cached_rev.get_relative_exp_path())

for tnick, tflags in TRANSLATORS:
    algo = FastDownwardAlgorithm(tnick, cached_rev, DRIVER_COMMON + tflags, [])
    for task in suites.build_suite(BENCHMARKS_DIR, SUITE):
        exp.add_run(FastDownwardRun(exp, algo, task))

exp.add_parser(FastDownwardExperiment.EXITCODE_PARSER)
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_step("parse", exp.parse)
exp.add_fetcher(name="fetch")


ATTRIBUTES = [
    "error",
    "translator_time_done",
    "translator_peak_memory",
    "translator_variables", "translator_facts", "translator_mutex_groups",
    "translator_operators", "translator_axioms", "translator_task_size",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", ModernAbsoluteReport)
    report = cls(**kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute", attributes=ATTRIBUTES)
# Equivalence + per-attribute py-vs-cpp comparison (shows any task whose
# output statistics differ between the two translators).
add_report(
    "compare-py-vs-cpp",
    cls=project.ComparativeReport,
    attributes=ATTRIBUTES,
    algorithm_pairs=[("py", "cpp")],
)
# Scatter plots only make sense for measurable times: the translator
# reports 0.00 s for sub-5 ms tasks, a log/relative plot needs values > 0,
# and the relative plot needs BOTH translators to have a value for a task.
# Keep every run (so each task still has its two runs) but null out
# non-positive times, which makes the report skip those (incomplete) pairs
# instead of erroring on a half-filtered task.
def positive_time(run):
    t = run.get("translator_time_done")
    if t is None or t <= 0:
        run["translator_time_done"] = None
    return run


# Relative scatter plot of translation time: x = py time, y = cpp/py ratio.
exp.add_report(
    ScatterPlotReport(
        attributes=["translator_time_done"],
        filter_algorithm=["py", "cpp"],
        filter=positive_time,
        relative=True,
        format="png",
    ),
    outfile=os.path.join(exp.eval_dir, "scatter-translator-time-relative.png"),
    name="scatter-relative",
)
# Also a standard log-log scatter for reference.
exp.add_report(
    ScatterPlotReport(
        attributes=["translator_time_done"],
        filter_algorithm=["py", "cpp"],
        filter=positive_time,
        format="png",
    ),
    outfile=os.path.join(exp.eval_dir, "scatter-translator-time.png"),
    name="scatter-absolute",
)

exp.run_steps()
