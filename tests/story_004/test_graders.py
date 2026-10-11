"""STORY-004 T4: the grader runtime (S4-06, and the mechanics every S4-05 row relies on).

The grader trusts nothing the contestant wrote except the declared files. Each guard is tested against
the attack that beats a grader without it, on its own layer, so a canary that removes one guard turns
this suite red even though the other guards are still there:

- layer 1, the copy: a planted `conftest.py`, `pytest.py` or `pytest.ini` never reaches the grading dir;
- layer 2, the run: `--noconftest`, `python -I` and the report rule each hold even if something planted
  got past the copy;
- the contestant's code runs in its own process, so an object equal to everything or a patched test
  runner cannot reach the assertion.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from keysbench.graders import TaskSpec, build_grading_dir, grade_pytest, grading_env, load_task, run_pytest

TASK_TOML = """
id = "KB-T"
family = "pytest"
editable = ["mod.py"]
expected_tests = ["test_hidden.py::test_add", "test_hidden.py::test_type"]
timeout_s = 60
"""

HIDDEN = """
from kbcall import call, strict_equal

def test_add():
    assert strict_equal(call("mod.add(2, 3)", "mod"), 5)

def test_type():
    assert strict_equal(call("mod.add(1, 1)", "mod"), 2)
"""

GOOD = "def add(a, b):\n    return a + b\n"
WRONG = "def add(a, b):\n    return 0\n"

# A conftest that rewrites every result to "passed": it beats any grader that loads it.
FORCE_PASS_CONFTEST = """
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    outcome.get_result().outcome = "passed"
"""

# A pytest.py that writes a report listing every test as passed and exits 0: it beats any grader that
# lets the directory shadow the real pytest.
FAKE_PYTEST = r"""
import pathlib, re, sys
out = [a.split("=", 1)[1] for a in sys.argv if a.startswith("--junitxml=")][0]
cases = "".join(
    f'<testcase classname="{f.stem}" name="{n}"/>'
    for f in pathlib.Path(".").glob("test_*.py")
    for n in re.findall(r"^def (test_\w+)", f.read_text(), re.M)
)
pathlib.Path(out).write_text(f'<testsuites><testsuite name="pytest">{cases}</testsuite></testsuites>')
sys.exit(0)
"""


def _task(tmp_path: Path, toml: str = TASK_TOML) -> Path:
    task = tmp_path / "task"
    (task / "tests").mkdir(parents=True, exist_ok=True)
    (task / "task.toml").write_text(toml, encoding="utf-8")
    (task / "tests" / "test_hidden.py").write_text(textwrap.dedent(HIDDEN), encoding="utf-8")
    return task


def _workspace(tmp_path: Path, files: dict[str, str]) -> Path:
    w = tmp_path / "w"
    w.mkdir()
    for name, text in files.items():
        (w / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return w


def _built(tmp_path: Path, mod: str = WRONG) -> tuple[TaskSpec, Path]:
    spec = load_task(_task(tmp_path))
    assert spec.path is not None
    dest = tmp_path / "g"
    build_grading_dir(spec, spec.path, _workspace(tmp_path, {"mod.py": mod}), dest)
    return spec, dest


def test_load_task_reads_the_declared_contract(tmp_path):
    spec = load_task(_task(tmp_path))
    assert (spec.id, spec.family, spec.editable, spec.timeout_s) == ("KB-T", "pytest", ("mod.py",), 60)
    assert spec.expected_tests == ("test_hidden.py::test_add", "test_hidden.py::test_type")


def test_a_correct_solution_passes(tmp_path):
    result = grade_pytest(load_task(_task(tmp_path)), _workspace(tmp_path, {"mod.py": GOOD}), tmp_path / "g")
    assert result.passed, result
    assert result.failed_checks == ()


def test_a_wrong_solution_fails_naming_the_tests(tmp_path):
    result = grade_pytest(load_task(_task(tmp_path)), _workspace(tmp_path, {"mod.py": WRONG}), tmp_path / "g")
    assert not result.passed
    assert set(result.failed_checks) == {"test_add", "test_type"}


# ── layer 1: the copy ───────────────────────────────────────────────────────────────────────────────


def test_s4_06_only_declared_files_are_copied(tmp_path):
    w = _workspace(
        tmp_path,
        {"mod.py": GOOD, "conftest.py": FORCE_PASS_CONFTEST, "pytest.py": FAKE_PYTEST, "pytest.ini": "[pytest]\n"},
    )
    result = grade_pytest(load_task(_task(tmp_path)), w, tmp_path / "g")
    code = sorted(p.name for p in (tmp_path / "g" / "code").iterdir())
    tests = sorted(p.name for p in (tmp_path / "g" / "tests").iterdir() if p.is_file())
    # The two never mix: the container that runs the contestant's code mounts only code/.
    assert (code, tests) == (["mod.py"], ["kbcall.py", "test_hidden.py"]), (code, tests)
    assert result.passed


def test_s4_06_non_editable_files_come_from_the_pristine_environment(tmp_path):
    # A task's other files (a package the editable file belongs to) come from the task's own copy, never
    # from the workspace: editing a file that is not declared changes nothing the grader runs.
    task = _task(tmp_path)
    (task / "environment").mkdir()
    (task / "environment" / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    (task / "environment" / "mod.py").write_text("def add(a, b):\n    return 0\n", encoding="utf-8")
    (task / "tests" / "test_hidden.py").write_text(
        "from kbcall import call\n"
        "def test_add():\n    assert call('mod.add(2, 3)', 'mod') == 5\n"
        "def test_type():\n    assert call('helper.VALUE', 'helper') == 2\n",
        encoding="utf-8",
    )
    w = _workspace(tmp_path, {"mod.py": GOOD, "helper.py": "VALUE = 99\n"})
    result = grade_pytest(load_task(task), w, tmp_path / "g")
    assert result.passed, result
    assert (tmp_path / "g" / "code" / "helper.py").read_text("utf-8") == "VALUE = 2\n"


def test_layer1_a_wrong_solution_with_planted_files_still_fails(tmp_path):
    w = _workspace(tmp_path, {"mod.py": WRONG, "conftest.py": FORCE_PASS_CONFTEST, "pytest.py": FAKE_PYTEST})
    assert not grade_pytest(load_task(_task(tmp_path)), w, tmp_path / "g").passed


# ── layer 2: the run holds even if something planted got past the copy ─────────────────────────────


def test_layer2_noconftest_holds_even_if_a_conftest_got_in(tmp_path):
    spec, dest = _built(tmp_path)
    (dest / "tests" / "conftest.py").write_text(FORCE_PASS_CONFTEST, encoding="utf-8")
    assert not run_pytest(spec, dest).passed


def test_layer2_isolated_mode_holds_even_if_a_pytest_py_got_in(tmp_path):
    spec, dest = _built(tmp_path)
    (dest / "tests" / "pytest.py").write_text(FAKE_PYTEST, encoding="utf-8")
    assert not run_pytest(spec, dest).passed


def test_s4_06_an_exit_zero_without_a_report_is_a_fail(tmp_path):
    spec, dest = _built(tmp_path, GOOD)
    (dest / "tests" / "test_hidden.py").write_text("import os\nos._exit(0)\n", encoding="utf-8")
    result = run_pytest(spec, dest)
    assert not result.passed and result.failed_checks == ("no_report",)


def test_s4_06_a_partial_report_is_a_fail(tmp_path):
    task = load_task(_task(tmp_path))
    spec = TaskSpec(**{**task.__dict__, "expected_tests": (*task.expected_tests, "test_hidden.py::test_missing")})
    result = grade_pytest(spec, _workspace(tmp_path, {"mod.py": GOOD}), tmp_path / "g")
    assert not result.passed
    assert result.failed_checks == ("test_missing",)


def test_a_skipped_test_is_not_a_pass(tmp_path):
    spec, dest = _built(tmp_path, GOOD)
    (dest / "tests" / "test_hidden.py").write_text(
        "import pytest\n@pytest.mark.skip\ndef test_add():\n    pass\ndef test_type():\n    pass\n", encoding="utf-8"
    )
    result = run_pytest(spec, dest)
    assert not result.passed and result.failed_checks == ("test_add",)


# ── the contestant's code runs in its own process ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mod",
    [
        "class E:\n    def __eq__(self, o):\n        return True\ndef add(a, b):\n    return E()\n",
        "import _pytest.runner as r\nr.call_and_report = lambda *a, **k: None\ndef add(a, b):\n    return 0\n",
        "def add(a, b):\n    return float(a + b)\n",  # the right value, the wrong type
    ],
    ids=["hack-eq-always", "hack-patch-runtest", "wrong-type"],
)
def test_contestant_code_cannot_reach_the_assertion(tmp_path, mod):
    result = grade_pytest(load_task(_task(tmp_path)), _workspace(tmp_path, {"mod.py": mod}), tmp_path / "g")
    assert not result.passed


# ── environment and time ───────────────────────────────────────────────────────────────────────────


def test_s4_06_the_grading_run_sees_no_credential(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("CREDENTIALS_FILE", "C:/secrets/.env")
    env = grading_env()
    assert "ANTHROPIC_API_KEY" not in env and "CREDENTIALS_FILE" not in env
    task = _task(tmp_path)
    (task / "tests" / "test_hidden.py").write_text(
        "import os\n"
        "from kbcall import call\n"
        "def test_add():\n"
        "    assert 'ANTHROPIC_API_KEY' not in os.environ and 'CREDENTIALS_FILE' not in os.environ\n"
        '    names = call(\'[k for k in __import__("os").environ if k.startswith(("ANTH", "CRED"))]\', \'mod\')\n'
        "    assert names == []\n"
        "def test_type():\n"
        "    pass\n",
        encoding="utf-8",
    )
    result = grade_pytest(load_task(task), _workspace(tmp_path, {"mod.py": GOOD}), tmp_path / "g")
    assert result.passed, result


def test_a_hanging_solution_times_out_as_a_fail(tmp_path):
    task = _task(tmp_path, TASK_TOML.replace("timeout_s = 60", "timeout_s = 3"))
    hang = "import time\ndef add(a, b):\n    time.sleep(30)\n"
    result = grade_pytest(load_task(task), _workspace(tmp_path, {"mod.py": hang}), tmp_path / "g")
    assert not result.passed
    assert result.failed_checks == ("timeout",)


def test_strict_equal_distinguishes_bool_int_and_float():
    from keysbench.kbcall import strict_equal

    assert strict_equal(1, 1) and not strict_equal(True, 1) and not strict_equal(1, 1.0)
    assert strict_equal(1.0, 1.0004, tol=1e-3) and not strict_equal(1.0, 1.01, tol=1e-3)
    assert strict_equal({"a": [1, "x"]}, {"a": [1, "x"]}) and not strict_equal({"a": 1}, {"a": 1, "b": 2})


# ── the container holds only the code under test ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mod",
    [
        # reads the hidden tests from the grading directory (passed on the first layout)
        "import pathlib\n"
        "def add(a, b):\n"
        "    for d in ('/code', '/code/..', '/tests', '/grading', '/work', '/tmp'):\n"
        "        for p in pathlib.Path(d).glob('**/test_hidden.py'):\n"
        "            return 5 if a == 2 else 2\n"
        "    return 0\n",
        # needs the network (pypi.org:443 connects from a container with the default network; a DNS
        # server on port 53 over TCP was refused even then, so it could not tell the two cases apart)
        "import socket\n"
        "def add(a, b):\n"
        "    socket.create_connection(('pypi.org', 443), timeout=5).close()\n"
        "    return a + b\n",
        # writes outside /tmp
        "def add(a, b):\n    open('/code/x', 'w').write('x')\n    return a + b\n",
    ],
    ids=["reads-hidden-tests", "network", "writes-the-code-dir"],
)
def test_the_contestants_code_reaches_only_its_own_files(tmp_path, mod):
    result = grade_pytest(load_task(_task(tmp_path)), _workspace(tmp_path, {"mod.py": mod}), tmp_path / "g")
    assert not result.passed, result
