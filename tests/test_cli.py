"""The command line as a contract: exit statuses, JSON errors, the schema, logging."""
import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from neosloc import __version__, cli
from neosloc.errors import EXIT_EVALUATOR, EXIT_INTERNAL, EXIT_OK, EXIT_PATH, EXIT_USAGE
from neosloc.log import logger
from neosloc.schema import ERROR_CODES, SCHEMA_VERSION, schema
from tests.test_agentic import service

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*argv, env=None):
    """Run cli.main in-process; return (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    logger.handlers[:] = []
    with redirect_stdout(out), redirect_stderr(err), mock.patch.dict(os.environ, env or {}, clear=False), \
            mock.patch.object(sys, "stderr", err):
        status = cli.main(list(argv))
    return status, out.getvalue(), err.getvalue()


def validate(doc):
    """Validate against the published schema (full validator when available)."""
    if jsonschema is not None:
        jsonschema.Draft202012Validator(schema()).validate(doc)
    else:  # structural minimum on Python 3.8 without jsonschema
        items = doc if isinstance(doc, list) else [doc]
        for d in items:
            assert d["schema_version"] == SCHEMA_VERSION
            assert ("error" in d) or {"target", "dimensions", "estimate"} <= set(d)


class Base(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        service(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)
        logger.handlers[:] = []


class Success(Base):
    def test_text_report(self):
        status, out, err = run(self.dir)
        self.assertEqual(status, EXIT_OK)
        self.assertIn("neosloc integrability report", out)
        self.assertEqual(err, "")  # static runs are silent on stderr at the default level

    def test_json_report_validates(self):
        status, out, _ = run("--json", self.dir)
        self.assertEqual(status, EXIT_OK)
        doc = json.loads(out)
        validate(doc)
        self.assertEqual(doc["schema_version"], SCHEMA_VERSION)
        self.assertEqual(len(doc["dimensions"]), 10)

    def test_only_and_multiple_paths(self):
        other = tempfile.mkdtemp()
        try:
            status, out, _ = run("--json", "--only", "interface,legibility", self.dir, other)
        finally:
            shutil.rmtree(other)
        docs = json.loads(out)
        validate(docs)
        self.assertEqual([[d["key"] for d in r["dimensions"]] for r in docs], [["interface", "legibility"]] * 2)

    def test_schema_command(self):
        status, out, _ = run("--schema")
        self.assertEqual(status, EXIT_OK)
        doc = json.loads(out)
        self.assertEqual(doc, schema())
        if jsonschema is not None:
            jsonschema.Draft202012Validator.check_schema(doc)

    def test_version(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as cm:
            cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn(__version__, out.getvalue())


class Errors(Base):
    def assert_json_error(self, out, code, status):
        doc = json.loads(out)
        validate(doc)
        self.assertEqual(doc["error"]["code"], code)
        self.assertEqual(doc["error"]["exit_status"], status)
        self.assertIn(code, ERROR_CODES)
        return doc

    def test_not_a_directory(self):
        status, out, err = run("--json", os.path.join(self.dir, "missing"))
        self.assertEqual(status, EXIT_PATH)
        doc = self.assert_json_error(out, "not_a_directory", EXIT_PATH)
        self.assertTrue(doc["target"].endswith("missing"))
        self.assertIn("not a directory", err)

    def test_not_a_directory_text_mode(self):
        status, out, err = run(os.path.join(self.dir, "missing"))
        self.assertEqual((status, out), (EXIT_PATH, ""))
        self.assertIn("not a directory", err)

    def test_partial_failure_keeps_good_reports(self):
        status, out, _ = run("--json", self.dir, os.path.join(self.dir, "missing"))
        self.assertEqual(status, EXIT_PATH)
        docs = json.loads(out)
        validate(docs)
        self.assertIn("dimensions", docs[0])
        self.assertEqual(docs[1]["error"]["code"], "not_a_directory")

    def test_usage_errors(self):
        for argv, code in [(["--frobnicate"], "usage"), ([], "usage"),
                           (["--only", "bogus", "."], "unknown_dimension"),
                           (["--agentic", "--tasks", "nope", "."], "unknown_task"),
                           (["--agentic", "--probe-model", "gpt5", "."], "bad_model_spec"),
                           (["--agentic", ".", "."], "usage")]:
            status, out, _ = run("--json", *argv)
            self.assertEqual(status, EXIT_USAGE, argv)
            self.assert_json_error(out, code, EXIT_USAGE)

    def test_usage_error_text_mode(self):
        status, out, err = run("--frobnicate")
        self.assertEqual((status, out), (EXIT_USAGE, ""))
        self.assertIn("unrecognized arguments", err)

    def test_evaluator_errors(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENROUTER_API_KEY", None)
            status, out, _ = run("--json", "--review", "--review-model", "openrouter:x/y", self.dir)
        self.assertEqual(status, EXIT_EVALUATOR)
        self.assert_json_error(out, "credentials", EXIT_EVALUATOR)

    def test_missing_sdk(self):
        with mock.patch.dict(sys.modules, {"anthropic": None}):
            status, out, _ = run("--json", "--agentic", "--tasks", "auth", self.dir)
        self.assertEqual(status, EXIT_EVALUATOR)
        self.assert_json_error(out, "missing_dependency", EXIT_EVALUATOR)

    def test_internal_error_is_reported_in_shape(self):
        with mock.patch.object(cli, "analyze", side_effect=RuntimeError("boom")):
            status, out, err = run("--json", self.dir)
        self.assertEqual(status, EXIT_INTERNAL)
        doc = self.assert_json_error(out, "internal", EXIT_INTERNAL)
        self.assertIn("boom", doc["error"]["message"])

    def test_interrupt(self):
        with mock.patch.object(cli, "analyze", side_effect=KeyboardInterrupt):
            status, out, _ = run("--json", self.dir)
        self.assertEqual(status, 130)
        self.assert_json_error(out, "interrupted", 130)


class Logging(Base):
    def test_debug_shows_detector_timings(self):
        status, _, err = run("--log-level", "debug", self.dir)
        self.assertEqual(status, EXIT_OK)
        self.assertIn("dimension interface:", err)
        self.assertIn("assessed", err)

    def test_env_var_level(self):
        _, _, err = run(self.dir, env={"NEOSLOC_LOG_LEVEL": "debug"})
        self.assertIn("dimension legibility", err)

    def test_bad_env_level_is_a_usage_error(self):
        status, out, _ = run("--json", self.dir, env={"NEOSLOC_LOG_LEVEL": "loud"})
        self.assertEqual(status, EXIT_USAGE)
        self.assertEqual(json.loads(out)["error"]["code"], "usage")

    def test_json_log_lines(self):
        _, _, err = run("--log-level", "debug", "--log-format", "json", self.dir)
        lines = [json.loads(l) for l in err.splitlines()]
        timing = next(l for l in lines if l.get("dimension") == "interface")
        self.assertEqual(timing["level"], "debug")
        self.assertIn("seconds", timing)
        self.assertIn("dimension_level", timing)
        self.assertTrue(timing["ts"].endswith("Z"))

    def test_extras_never_overwrite_standard_keys(self):
        from neosloc.log import configure
        stream = io.StringIO()
        configure("info", "json", stream)
        logger.info("hello", extra={"level": 3, "message_id": 1})
        line = json.loads(stream.getvalue())
        self.assertEqual((line["level"], line["extra_level"], line["message"]), ("info", 3, "hello"))

    def test_json_error_log_line(self):
        _, _, err = run("--log-format", "json", os.path.join(self.dir, "missing"))
        line = json.loads(err.strip().splitlines()[-1])
        self.assertEqual((line["level"], line["code"], line["exit_status"]), ("error", "not_a_directory", 3))

    def test_quiet_hides_progress_but_not_errors(self):
        from neosloc.agentic import Probe
        logger.handlers[:] = []
        status, _, err = run("-q", "--log-level", "debug", self.dir)  # -q wins
        self.assertEqual((status, err), (EXIT_OK, ""))
        _, _, err = run("-q", os.path.join(self.dir, "missing"))
        self.assertIn("not a directory", err)
        self.assertTrue(Probe)

    def test_evaluator_progress_is_info(self):
        from neosloc.log import configure
        stream = io.StringIO()
        configure("info", stream=stream)
        logger.info("probe x docs/auth ...")
        configure("warning", stream=stream)
        logger.info("hidden")
        self.assertEqual(stream.getvalue().strip().splitlines(), ["neosloc: probe x docs/auth ..."])
        self.assertEqual(logger.level, logging.WARNING)


class Subprocess(unittest.TestCase):
    """The installed entry point behaves like main()."""

    def test_module_entry_point(self):
        env = dict(os.environ, PYTHONPATH=ROOT)
        p = subprocess.run([sys.executable, "-m", "neosloc", "--json", "/nonexistent-neosloc-path"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        self.assertEqual(p.returncode, EXIT_PATH)
        self.assertEqual(json.loads(p.stdout)["error"]["code"], "not_a_directory")


if __name__ == "__main__":
    unittest.main()
