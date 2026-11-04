"""Run the full unittest discovery with fresh processes for each test module.

Qt keeps closed widgets alive while Python references or callbacks retain them.
Isolating modules prevents later theme tests from repolishing hundreds of old
windows. The discovered test IDs, assertions and exit status remain unchanged.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
RESULT_MARKER = "LUXAI_TEST_RESULT="


def configure_output():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")


def import_paths(start_directory):
    # Discovery also permits imports of sibling test helpers without a
    # `tests.` prefix. Match that behavior in every fresh child process.
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(start_directory))


def test_cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from test_cases(item)
        else:
            yield item


def child():
    request = json.load(sys.stdin)
    import_paths(Path(request["directory"]))
    suite = unittest.defaultTestLoader.loadTestsFromNames(request["tests"])
    discovered = suite.countTestCases()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("\n" + RESULT_MARKER + json.dumps({
        "discovered": discovered,
        "run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
    }), flush=True)
    # Some headless Qt/native plugins can fault during interpreter teardown.
    # All test assertions and unittest cleanup have already finished here.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if result.wasSuccessful() else 1)


def run_module(item, directory, timeout):
    module, tests = item
    print(f"Running {module} ({len(tests)} tests)", flush=True)
    environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--child"],
            input=json.dumps({"directory": str(directory), "tests": tests}).encode("utf-8"),
            cwd=ROOT, env=environment, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout,
        )
        output = completed.stdout.decode("utf-8", errors="replace")
        reports = [line[len(RESULT_MARKER):] for line in output.splitlines()
                   if line.startswith(RESULT_MARKER)]
        metrics = json.loads(reports[-1]) if reports else None
        if metrics is None or metrics["discovered"] != len(tests):
            raise ValueError(f"Missing or incomplete results; process exit {completed.returncode}")
        return module, metrics, completed.returncode, output
    except subprocess.TimeoutExpired as error:
        output = (error.stdout or b"").decode("utf-8", errors="replace")
        output += f"\nERROR: {module} exceeded {timeout} seconds.\n"
    except (OSError, ValueError, KeyError, TypeError) as error:
        output = locals().get("output", "") + f"\nERROR: {module}: {error}\n"
    return module, {"discovered": len(tests), "run": 0, "failures": 0, "errors": 1, "skipped": 0,
                    "expected_failures": 0, "unexpected_successes": 0}, 1, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=2)
    parser.add_argument("--timeout", type=int, default=180, help="Maximum seconds per module")
    parser.add_argument("--start-directory", type=Path, default=ROOT / "tests")
    parser.add_argument("--pattern", default="test*.py")
    options = parser.parse_args()
    if options.timeout <= 0:
        parser.error("--timeout must be positive")
    directory = options.start_directory.resolve()
    import_paths(directory)
    loader = unittest.TestLoader()
    suite = loader.discover(str(directory), pattern=options.pattern)
    modules = OrderedDict()
    for case in test_cases(suite):
        if isinstance(case, unittest.loader._FailedTest):
            continue  # The loader's original traceback is printed below.
        modules.setdefault(case.__class__.__module__, []).append(case.id())
    discovery_errors = list(loader.errors)
    del suite
    started = time.monotonic()
    totals = {key: 0 for key in ("discovered", "run", "failures", "errors", "skipped",
                                "expected_failures", "unexpected_successes")}
    totals["errors"] = len(discovery_errors)
    failed = []
    for error in discovery_errors:
        print(error, file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=options.workers) as pool:
        results = pool.map(lambda item: run_module(item, directory, options.timeout), modules.items())
        for module, metrics, returncode, output in results:
            print(f"\n===== {module} =====\n{output}", flush=True)
            for key in totals:
                totals[key] += metrics[key]
            if returncode:
                failed.append(module)
    elapsed = time.monotonic() - started
    print(f"\nRan {totals['run']} tests across {len(modules)} modules in {elapsed:.1f}s", flush=True)
    success = not (failed or discovery_errors)
    print(("OK" if success else "FAILED") + " " + json.dumps(totals), flush=True)
    if failed:
        print("Failed modules: " + ", ".join(failed), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    configure_output()
    if sys.argv[1:] == ["--child"]:
        child()
    sys.exit(main())
