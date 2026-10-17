"""The three CLI seats whose answer is a structured field, not the raw text (worker 25, backlog T145).

claude_cli, qoder_cli and antigravity_cli read `structured_output` (antigravity also undoes its schema rewrite). The
raw text is something else, so a replay that re-reads raw cannot reproduce the answer the council used. The fix logs
what each connector used, as `structured`, and the replay returns it.

Each test runs the real connector against stub CLI output (cli_common.run is replaced; no CLI or model is called).
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from karamaniya.backends import cli_common  # noqa: E402
from karamaniya.backends.antigravity_cli import AntigravityCLIBackend  # noqa: E402
from karamaniya.backends.base import CallResult  # noqa: E402
from karamaniya.backends.claude_cli import ClaudeCLIBackend  # noqa: E402
from karamaniya.backends.qoder_cli import QoderCLIBackend  # noqa: E402
from karamaniya.backends.replay import ReplayBackend  # noqa: E402

SYSTEM = "STANDING INSTRUCTIONS FOR THE TEST"
USER = "Vote on the motion."
SCHEMA = {"type": "object", "properties": {"vote": {"type": "string", "enum": ["yes", "no", "abstain"]},
                                           "reason": {"type": "string"}},
          "required": ["vote", "reason"], "additionalProperties": False}
ANSWER = {"vote": "no", "reason": "No. Raising taxes now deepens the slump."}
CONTEXT = {"phase": "decision", "member": "A"}


def _claude_stdout(result_text, structured):
    event = {"type": "result", "is_error": False, "result": result_text, "stop_reason": "end_turn",
             "usage": {"input_tokens": 120, "output_tokens": 12}, "modelUsage": {"claude-test": {}}}
    if structured is not None:
        event["structured_output"] = structured
    return json.dumps({"type": "system", "subtype": "init"}) + "\n" + json.dumps(event) + "\n"


class ThreeSeatsReplayWhatTheyUsed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-cli-replay-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def replay_of(self, provider, records):
        """A replay seat over a log holding `records`, as the council writes them (month, phase, member, to_dict())."""
        path = os.path.join(self.tmp, "log.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            for rec in records:
                f.write(json.dumps({"type": "call", "month": 3, "phase": "decision", "member": "A", **rec}) + "\n")
        return ReplayBackend({"replay_of": provider, "replay_log": path, "model": "replayed"})

    def replayed(self, provider, res):
        seat = self.replay_of(provider, [res.to_dict()])
        return seat.complete(SYSTEM, USER, SCHEMA, {"world": SimpleNamespace(month=3), **CONTEXT})

    def test_claude_logs_the_structured_answer_and_the_replay_returns_it(self):
        stdout = _claude_stdout("Voting no on the motion.", ANSWER)
        with mock.patch.object(cli_common, "run", return_value=(0, stdout, "")):
            res = ClaudeCLIBackend({"cli_command": ["claude-stub"], "model": "claude-test", "retries": 0}).call(
                SYSTEM, USER, SCHEMA, dict(CONTEXT))
        self.assertEqual(res.data, ANSWER)
        self.assertNotEqual(res.raw, json.dumps(ANSWER), "the stub must make raw differ from the structured answer")
        self.assertEqual(res.to_dict()["structured"], ANSWER)
        replayed = self.replayed("claude_cli", res)
        self.assertEqual(replayed.data, ANSWER)

    def test_claude_without_a_structured_answer_replays_as_no_answer(self):
        # The connector read no structured answer (data None). Its raw text holds JSON, but the council never used it.
        stdout = _claude_stdout(json.dumps(ANSWER), None)
        with mock.patch.object(cli_common, "run", return_value=(0, stdout, "")):
            res = ClaudeCLIBackend({"cli_command": ["claude-stub"], "model": "claude-test", "retries": 0}).call(
                SYSTEM, USER, SCHEMA, dict(CONTEXT))
        self.assertIsNone(res.data)
        self.assertIsNone(self.replayed("claude_cli", res).data)

    def test_qoder_logs_the_structured_answer_and_the_replay_returns_it(self):
        stdout = json.dumps({"result": "Voting no.", "structured_output": ANSWER, "stop_reason": "end_turn",
                             "usage": {"input_tokens": 90, "output_tokens": 9}, "modelUsage": {"qoder-test": {}}})
        with mock.patch.object(cli_common, "run", return_value=(0, stdout, "")):
            res = QoderCLIBackend({"cli_command": ["qoder-stub"], "model": "qoder-test", "retries": 0}).call(
                SYSTEM, USER, SCHEMA, dict(CONTEXT))
        self.assertEqual(res.data, ANSWER)
        self.assertEqual(res.to_dict()["structured"], ANSWER)
        self.assertEqual(self.replayed("qoder_cli", res).data, ANSWER)

    def test_antigravity_logs_the_restored_answer_and_the_replay_returns_it(self):
        # The schema's empty-string enum is sent to Gemini as "none"; the connector restores "" before the council reads it.
        schema = {"type": "object", "properties": {"office": {"type": "string", "enum": ["", "head"]}},
                  "required": ["office"], "additionalProperties": False}
        sent = {"office": "none"}
        events = [{"event": "init", "init": {"model": "gemini-test", "tools": []}},
                  {"event": "result", "result": {"status": "SUCCESS", "response": json.dumps(sent) + "\n",
                                                 "structured_output": sent, "num_turns": 2,
                                                 "usage": {"input_tokens": 40, "output_tokens": 4}}}]
        stdout = "\n".join(json.dumps(e) for e in events) + "\n"
        with mock.patch.object(cli_common, "run", return_value=(0, stdout, "")):
            res = AntigravityCLIBackend({"cli_command": ["agy-stub"], "model": "gemini-test", "retries": 0}).call(
                SYSTEM, USER, schema, dict(CONTEXT))
        self.assertEqual(res.data, {"office": ""})
        self.assertEqual(res.to_dict()["structured"], {"office": ""})
        replayed = self.replay_of("antigravity_cli", [res.to_dict()]).complete(
            SYSTEM, USER, schema, {"world": SimpleNamespace(month=3), **CONTEXT})
        self.assertEqual(replayed.data, {"office": ""})

    def test_a_replayed_connector_answer_is_the_one_the_council_reads_back(self):
        # The council maps seeded names back after the connector, on the connector's answer. The replay must hand
        # the connector's answer, not the mapped one, so the council maps it exactly once, as it did in the run.
        stdout = _claude_stdout("Voting no.", ANSWER)
        with mock.patch.object(cli_common, "run", return_value=(0, stdout, "")):
            res = ClaudeCLIBackend({"cli_command": ["claude-stub"], "model": "claude-test", "retries": 0}).call(
                SYSTEM, USER, SCHEMA, dict(CONTEXT))
        self.assertEqual(self.replayed("claude_cli", res).data, res.data)


class RecordsWithoutTheField(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="karamaniya-cli-replay-old-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_other_seats_log_no_structured_field(self):
        res = CallResult(data=ANSWER, raw=json.dumps(ANSWER))
        self.assertNotIn("structured", res.to_dict())
        self.assertNotIn("structured_read", res.to_dict())

    def test_a_record_without_the_field_replays_from_raw_as_before(self):
        path = os.path.join(self.tmp, "log.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps({"type": "call", "month": 3, "phase": "decision", "member": "A",
                                "raw": json.dumps(ANSWER), "served_model": "old"}) + "\n")
        seat = ReplayBackend({"replay_of": "claude_cli", "replay_log": path, "model": "replayed"})
        res = seat.complete(SYSTEM, USER, SCHEMA, {"world": SimpleNamespace(month=3), **CONTEXT})
        self.assertEqual(res.data, ANSWER)


if __name__ == "__main__":
    unittest.main()
