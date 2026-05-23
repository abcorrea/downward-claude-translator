#! /usr/bin/env python3
"""Full-pipeline (translate + search) comparison: C++ port vs Python translator.

Structure mirrors Scorpion's
`experiments/2026-01-preprocessor/2026-01-08-A-preprocessor-optimizations.py`:

  - SUITE depends on whether we're running on a known compute cluster
    (REMOTE) or locally. Remote: pull the canonical SUITE_SATISFICING
    from `project.py` and resolve via $DOWNWARD_BENCHMARKS. Local: use
    the bundled mini-suite under `misc/tests/benchmarks/`.
  - ENV is chosen the same way (TetralithEnvironment vs LocalEnvironment).
  - Two "algorithms" — both invoke the in-tree fast-downward.py; they
    differ only in `--translator cpp` vs `--translator py`, a driver
    flag the port added to `driver/arguments.py`.

Implementation note: lab 4.2's `FastDownwardExperiment.add_algorithm`
uses Mercurial-backed `CachedRevision`, which doesn't fit this repo
(git). We bypass it by subclassing `Run` and pointing it at the
working tree's `fast-downward.py`; the FastDownwardExperiment is still
useful for its bundled parsers and the build/start/parse/fetch step
scaffold.
"""
import os
from pathlib import Path

import project

from downward import suites
from downward.experiment import FastDownwardExperiment
from lab.experiment import Experiment, Run


# --- Repository + benchmarks --------------------------------------------------
#
# Local: tiny smoke-test suite (matches Scorpion's
# `experiments/.../*-A-preprocessor-optimizations.py` shape, which uses
# 3 instances locally and the full satisficing suite remotely).
SUITE = [
    "gripper:prob01.pddl",
    "miconic:s1-0.pddl",
]

if project.REMOTE:
    BENCHMARKS_DIR = os.environ["DOWNWARD_BENCHMARKS"]
    SUITE = project.SUITE_SATISFICING
    ENV = project.TetralithEnvironment(
        memory_per_cpu="3584M",
        # Override these in a remote checkout:
        # email="user@example.com",
        # extra_options="#SBATCH --account=naissXXXX-Y-ZZZ",
    )
else:
    project.assert_local_paths_exist()
    BENCHMARKS_DIR = str(project.LOCAL_BENCHMARKS_DIR)
    ENV = project.LocalEnvironment(processes=2)


# --- Algorithms & configurations ---------------------------------------------

TIME_LIMIT_S = 120
MEM_LIMIT_MB = 2048

# Driver flags shared by every run.
DRIVER_OPTIONS_COMMON = [
    "--validate",
    "--overall-time-limit", f"{TIME_LIMIT_S}s",
    "--overall-memory-limit", f"{MEM_LIMIT_MB}M",
]

# Search configs. lazy_greedy + FF is fast enough for both the local
# mini-suite and the satisficing suite.
CONFIGS = [
    ("lazy-ff", ["--search", "lazy_greedy([ff()], preferred=[ff()])"]),
]

TRANSLATOR_VARIANTS = ["cpp", "py"]


class TranslateAndSearchRun(Run):
    """Invoke `fast-downward.py --translator <X> [config] <dom> <prob>`.

    The driver flag --translator was added to driver/arguments.py so we
    can switch translator backends without env-var gymnastics.
    """

    def __init__(self, exp, algo_name, translator, config_opts, task):
        super().__init__(exp)
        self.algo_name = algo_name
        self.task = task
        self.set_property("id", [algo_name, task.domain,
                                 Path(task.problem_file).stem])
        self.set_property("algorithm", algo_name)
        self.set_property("domain", task.domain)
        self.set_property("problem", task.problem)
        self.set_property("translator", translator)
        self.set_property("time_limit", TIME_LIMIT_S)
        self.set_property("memory_limit", MEM_LIMIT_MB * 1024)
        # Make the input files visible to Lab so they show up in run dir
        # listings (purely cosmetic; the planner reads them from their
        # original paths below).
        self.add_resource(
            "domain", task.domain_file, "domain.pddl", symlink=True)
        self.add_resource(
            "problem", task.problem_file, "problem.pddl", symlink=True)
        cmd = [
            str(project.FAST_DOWNWARD),
            "--translator", translator,
            *DRIVER_OPTIONS_COMMON,
            str(task.domain_file),
            str(task.problem_file),
            *config_opts,
        ]
        self.add_command(
            "planner", cmd,
            time_limit=TIME_LIMIT_S,
            memory_limit=MEM_LIMIT_MB * 1024,
        )


# --- Experiment ---------------------------------------------------------------

# Use the base Experiment class -- FastDownwardExperiment requires
# `add_algorithm`, which uses lab 4.2's hg-only CachedRevision. We still
# reference FastDownwardExperiment's class-level parser constants below.
exp = Experiment(environment=ENV)

tasks = list(suites.build_suite(BENCHMARKS_DIR, SUITE))
for translator in TRANSLATOR_VARIANTS:
    for cnick, cconfig in CONFIGS:
        algo_name = f"{translator}-{cnick}"
        for task in tasks:
            exp.add_run(TranslateAndSearchRun(
                exp, algo_name, translator, cconfig, task))

# Lab's bundled parsers cover everything we care about; the custom
# parser adds the C++-specific [phase] timer lines.
exp.add_parser(FastDownwardExperiment.EXITCODE_PARSER)
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)
exp.add_parser(FastDownwardExperiment.SINGLE_SEARCH_PARSER)
exp.add_parser(str(project.DIR / "custom_parser.py"))
exp.add_parser(FastDownwardExperiment.PLANNER_PARSER)

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
exp.add_parse_again_step()
exp.add_fetcher(name="fetch")


# --- Reports -----------------------------------------------------------------

ATTRIBUTES = [
    # Identity / outcome.
    "error", "coverage", "planner_exit_code",
    "search_start_time", "search_start_memory", "total_time",
    "translator_total_time_cpp", "translator_total_time_py",
    # Translator output stats (emitted by both implementations).
    "translator_kind",
    "translator_variables", "translator_facts", "translator_mutex_groups",
    "translator_operators", "translator_axioms", "translator_task_size",
    "translator_peak_memory",
    # Search-side numbers.
    "expansions", "generated", "evaluations", "memory", "cost", "plan_length",
    # C++ phase timers (only populated for cpp-* algorithms).
    "cpp_phase_compute_model_time",
    "cpp_phase_instantiate_time",
    "cpp_phase_translate_strips_operators_time",
    "cpp_phase_simplify_time",
    "cpp_phase_write_time",
    "cpp_phase_pddl_to_sas_total_time",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", project.AbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
add_report(
    "compare-cpp-vs-py",
    cls=project.ComparativeReport,
    algorithm_pairs=[("py-lazy-ff", "cpp-lazy-ff")],
)

exp.run_steps()
