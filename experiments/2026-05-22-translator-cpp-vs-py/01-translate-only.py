#! /usr/bin/env python3
"""Translate-only comparison of the C++ port against the Python translator.

Each (algorithm, instance) run invokes `fast-downward.py --translate
<domain> <problem>`. The choice of translator is controlled via env
vars (FD_TRANSLATE_CPP / FD_TRANSLATE_PY) consumed by
driver/run_components.py.

Run locally:

    ./01-translate-only.py

Subsequent invocations re-use the existing `data/01-translate-only/`
directory; pass `--all` or one of the explicit step names ('build',
'start', 'parse', 'fetch', 'report') to run a particular phase.

Modelled after Scorpion's `experiments/.../*.py` layout.
"""
import os
import subprocess
from pathlib import Path

import custom_parser
import project

from downward import suites
from downward.experiment import FastDownwardExperiment
from downward.reports.absolute import AbsoluteReport
from downward.reports.compare import ComparativeReport
from lab.experiment import Experiment, Run


project.assert_paths_exist()

ENV = project.LocalEnvironment(processes=1)  # sequential, matches our 120s/2GiB suite limit

# All bundled instances. The list is computed in project.py from the
# benchmarks dir, so adding a new instance there picks it up automatically.
SUITE = project.LOCAL_SUITE

# Two algorithms: cpp uses the built C++ binary, py forces the Python translator.
ALGORITHMS = ["cpp", "py"]

# 120s wall, 2GiB virt — matches the project-wide constraint.
TIME_LIMIT_S = 120
MEM_LIMIT_KB = 2 * 1024 * 1024


class TranslateOnlyRun(Run):
    """Invoke `fast-downward.py --translate domain.pddl problem.pddl`.

    Lab's `add_command` has no per-run env-var hook, so we prepend
    `/usr/bin/env VAR=value …` to push FD_TRANSLATE_CPP /
    FD_TRANSLATE_PY into fast-downward.py's process. The driver
    (driver/run_components.py) consults those vars to decide which
    translator binary to invoke.
    """

    def __init__(self, exp, algo, problem):
        super().__init__(exp)
        self.algo = algo
        self.problem = problem
        env_vars = project.TRANSLATOR_ENV[algo]
        self.set_property("id", [algo, problem.domain, Path(problem.problem_file).stem])
        self.set_property("algorithm", algo)
        self.set_property("domain", problem.domain)
        self.set_property("problem", problem.problem)
        self.set_property("time_limit", TIME_LIMIT_S)
        self.set_property("memory_limit", MEM_LIMIT_KB)
        cmd = ["/usr/bin/env"] + [f"{k}={v}" for k, v in env_vars.items()] + [
            str(project.FAST_DOWNWARD),
            "--translate",
            str(problem.domain_file),
            str(problem.problem_file),
        ]
        self.add_command(
            "translate", cmd,
            time_limit=TIME_LIMIT_S,
            memory_limit=MEM_LIMIT_KB,
        )


exp = Experiment(environment=ENV)

for algo in ALGORITHMS:
    for task in suites.build_suite(str(project.BENCHMARKS_DIR), SUITE):
        exp.add_run(TranslateOnlyRun(exp, algo, task))

# Lab ships a translator parser that picks up "Translator vars: N" etc.
# from both Python's and our C++ port's output. Our custom parser adds
# the C++-specific [phase] X.Ys timer lines plus the translate exit
# code (the stock EXITCODE_PARSER looks for "planner exit code" which
# is only emitted in full-pipeline runs).
exp.add_parser(FastDownwardExperiment.TRANSLATOR_PARSER)
exp.add_parser(str(project.DIR / "custom_parser.py"))

exp.add_step("build", exp.build)
exp.add_step("start", exp.start_runs)
# In lab >=4.2 parsing happens automatically as the last command of each
# run (add_parser appends a parser invocation). For re-parsing without
# re-running:
exp.add_parse_again_step()
exp.add_fetcher(name="fetch")


ATTRIBUTES = [
    "algorithm",
    "domain",
    "problem",
    "error",
    "translate_exit_code",
    "translate_wall_clock_time",
    "translator_kind",
    "translator_total_time_cpp",
    "translator_total_time_py",
    "translator_variables",
    "translator_facts",
    "translator_mutex_groups",
    "translator_operators",
    "translator_axioms",
    "translator_task_size",
    "translator_peak_memory",
    "cpp_phase_compute_model_time",
    "cpp_phase_instantiate_time",
    "cpp_phase_translate_strips_operators_time",
    "cpp_phase_simplify_time",
    "cpp_phase_write_time",
    "cpp_phase_pddl_to_sas_total_time",
]


def add_report(name, **kwargs):
    cls = kwargs.pop("cls", AbsoluteReport)
    report = cls(attributes=ATTRIBUTES, **kwargs)
    outfile = os.path.join(exp.eval_dir, f"{name}.html")
    exp.add_report(report, outfile=outfile, name=name)


add_report("absolute")
add_report("compare-cpp-vs-py", cls=ComparativeReport,
           algorithm_pairs=[("py", "cpp")])

exp.run_steps()
