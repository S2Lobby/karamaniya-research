"""The control room server: its guards, keys, council files, and a run started, stopped and resumed."""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from karamaniya import envfile  # noqa: E402
from karamaniya import gui  # noqa: E402
from karamaniya.gui import Controller, compare, comparative_notes, make_server  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "test-token-123"
SECRET = "sk-test-value-9f8e7d"


class LiveDraft(unittest.TestCase):
    def test_live_feed_keeps_details_of_directive_violations(self):
        with tempfile.TemporaryDirectory(prefix="karamaniya-live-defiance-") as tmp:
            controller = Controller(Path(tmp), Path(tmp) / "runs")
            controller._new_job("run", "defiance", 1)
            detail = {"member": "D", "office": "army", "lever": "officer_pay",
                      "directive": 0.0, "value": 0.05}
            controller.observer({"type": "resolved", "month": 3, "motions": [], "defiance": 1,
                                 "defiance_details": [detail]})
            event = controller.live(0)["items"][-1]
            self.assertEqual(event["kind"], "resolved")
            self.assertEqual(event["defiance"], 1)
            self.assertEqual(event["defiance_details"], [detail])

    def test_public_speech_draft_is_visible_during_call(self):
        with tempfile.TemporaryDirectory(prefix="karamaniya-live-draft-") as tmp:
            controller = Controller(Path(tmp), Path(tmp) / "runs")
            controller._new_job("run", "draft", 1)
            controller.observer({"type": "call_start", "member": "A", "phase": "session", "month": 0})
            controller.observer({"type": "call_progress", "member": "A", "phase": "session", "month": 0,
                                 "preview": "We must protect the election."})
            call = controller.live(0)["job"]["calls"]["A"]
            self.assertEqual(call["preview"], "We must protect the election.")
            controller.observer({"type": "call_end", "member": "A", "phase": "session", "month": 0,
                                 "ok": True, "spend": 0})
            self.assertNotIn("A", controller.live(0)["job"]["calls"])

    def test_external_cabinet_call_is_visible_during_simulation(self):
        with tempfile.TemporaryDirectory(prefix="karamaniya-foreign-live-") as tmp:
            controller = Controller(Path(tmp), Path(tmp) / "runs")
            controller._new_job("run", "foreign", 1)
            controller.observer({"type": "simulate", "month": 0})
            controller.observer({"type": "foreign_call_start", "actor": "dorsania", "month": 0,
                                 "seat": "Space", "provider": "openrouter", "model": "stealth/space-bunny-alpha"})
            live = controller.live(0)["job"]
            self.assertEqual(live["phase"], "foreign_cabinets")
            self.assertEqual(live["foreign_calls"]["dorsania"]["seat"], "Space")
            self.assertGreaterEqual(live["foreign_calls"]["dorsania"]["elapsed"], 0)
            controller.observer({"type": "foreign_call_end", "actor": "dorsania", "month": 0,
                                 "seat": "Space", "provider": "openrouter", "ok": False,
                                 "error": "IncompleteRead", "spend": 0})
            live = controller.live(0)
            self.assertEqual(live["job"]["phase"], "simulate")
            self.assertEqual(live["job"]["done_calls"], 1)
            self.assertEqual(live["items"][-1]["kind"], "external_problem")


class ComparisonEligibility(unittest.TestCase):
    def test_formation_checkpoint_does_not_count_as_survival(self):
        card = {"country": {"months_run": 0}, "members": {"A": {"label": "model-A", "status": "active"}}}
        paused = {"id": "paused", "status": "paused", "card": card, "months_total": 3,
                  "mapping": {"A": "model-A"}, "spend": 0}
        result = compare([paused])
        self.assertEqual(result["models"], [])
        self.assertEqual(result["runs"], [])

    def test_seed_notes_require_identical_experimental_setup(self):
        card = {"country": {"outcome": {"type": "survived"}}, "analytics": {
            "metrics": {}, "factions": {}, "political_history": []}}
        base = {"status": "finished", "card": card, "mapping": {"A": "model-A"}, "months_done": 2}
        runs = [{**base, "id": "one", "comparison_cohort": "scenario-A"},
                {**base, "id": "two", "comparison_cohort": "scenario-B"}]
        self.assertEqual(comparative_notes(runs), [])
        runs[1]["comparison_cohort"] = "scenario-A"
        self.assertEqual(len(comparative_notes(runs)), 1)
        runs[1]["card"] = {**card, "analytics": {**card["analytics"],
                                                "political_history": [{"month": 0, "kind": "coup"}]}}
        self.assertEqual(comparative_notes(runs)[0]["first_divergence"]["month"], 0)


class LibraryReportFreshness(unittest.TestCase):
    def test_saved_report_is_marked_stale_when_checkpoint_has_more_months(self):
        with tempfile.TemporaryDirectory(prefix="karamaniya-report-freshness-") as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            (run / "config.json").write_text(json.dumps({"run": {"months": 36, "seed": 1}}), encoding="utf-8")
            (run / "checkpoint.json").write_text(json.dumps({
                "world": {"history": [{"month": 0}, {"month": 1}], "outcome": {}},
                "meta": {"stopped": ""}, "council": {"spend": 0},
            }), encoding="utf-8")
            (run / "scorecard.json").write_text(json.dumps({"country": {"months_run": 1}}), encoding="utf-8")
            (run / "report.html").write_text("saved report", encoding="utf-8")

            summary = gui.Library(Path(tmp)).summary(run)

        self.assertEqual(summary["months_done"], 2)
        self.assertEqual(summary["report_months"], 1)
        self.assertTrue(summary["has_report"])
        self.assertTrue(summary["report_stale"])

    def test_saved_report_with_matching_month_count_is_current(self):
        with tempfile.TemporaryDirectory(prefix="karamaniya-report-freshness-") as tmp:
            run = Path(tmp) / "run"
            run.mkdir()
            (run / "config.json").write_text(json.dumps({"run": {"months": 2}}), encoding="utf-8")
            (run / "checkpoint.json").write_text(json.dumps({
                "world": {"history": [{"month": 0}, {"month": 1}], "outcome": {}},
                "meta": {"stopped": ""}, "council": {},
            }), encoding="utf-8")
            (run / "scorecard.json").write_text(json.dumps({"country": {"months_run": 2}}), encoding="utf-8")
            (run / "report.html").write_text("saved report", encoding="utf-8")

            summary = gui.Library(Path(tmp)).summary(run)

        self.assertFalse(summary["report_stale"])


class ControlRoom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="karamaniya-gui-test-")
        shutil.copy(os.path.join(HERE, "council.scripted.toml"), cls.tmp)
        cls.runs = os.path.join(cls.tmp, "runs")
        cls.server = make_server(cls.tmp, cls.runs, port=0, token=TOKEN)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        c = cls.server.controller
        if c.busy() and c.stop_event is not None:
            c.stop_event.set()
            c.thread.join(timeout=60)
        cls.server.shutdown()
        cls.server.server_close()
        os.environ.pop("KARAMANIYA_GUI_TEST_KEY", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- plumbing --
    def req(self, method, path, body=None, token=TOKEN, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if token:
            h["X-Karamaniya-Token"] = token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        conn.close()
        return r.status, dict(r.getheaders()), raw

    def api(self, method, call, body=None, **query):
        path = "/api/" + call + ("?" + "&".join(f"{k}={v}" for k, v in query.items()) if query else "")
        status, _, raw = self.req(method, path, body)
        return status, json.loads(raw or b"{}")

    def wait_idle(self, timeout=180):
        end = time.time() + timeout
        while time.time() < end:
            _, live = self.api("GET", "live", since=0)
            if live["job"] and not live["job"]["active"]:
                return live
            time.sleep(0.2)
        self.fail("the run did not finish in time")

    def scripted_config(self, months):
        status, d = self.api("GET", "config", name="council.scripted.toml")
        self.assertEqual(status, 200)
        cfg = d["config"]
        cfg["run"].update(months=months, survey=False)
        return cfg

    # -- guards --
    def test_page_carries_token_and_nonce(self):
        status, headers, raw = self.req("GET", "/", token=None)
        self.assertEqual(status, 200)
        html = raw.decode()
        self.assertIn(TOKEN, html)
        self.assertNotIn("__TOKEN__", html)
        self.assertNotIn("__NONCE__", html)
        csp = headers["Content-Security-Policy"]
        nonce = csp.split("'nonce-")[1].split("'")[0]
        self.assertIn(f'nonce="{nonce}"', html)
        self.assertIn("frame-ancestors 'none'", csp)

    def test_qoder_model_discovery_returns_cli_canonical_names(self):
        with patch.object(gui, "discover_models", return_value=["Qwen3.8-Flash"]):
            status, d = self.api("GET", "models", provider="qoder_cli")
        self.assertEqual(status, 200)
        self.assertTrue(d["found"])
        self.assertEqual(d["models"], ["Qwen3.8-Flash"])
        _, _, raw = self.req("GET", "/")
        self.assertIn("exact, case-sensitive model id", raw.decode())

    def test_map_front_summary_labels_effective_field_strength(self):
        _, _, raw = self.req("GET", "/")
        self.assertIn("effective field strength vs", raw.decode())

    def test_live_chamber_photo_is_served_locally(self):
        status, headers, raw = self.req("GET", "/council-chamber.png", token=None)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_refuses_strangers(self):
        self.assertEqual(self.req("GET", "/api/state", token=None)[0], 403)
        self.assertEqual(self.req("GET", "/api/state", token="wrong")[0], 403)
        # DNS rebinding: a page on another name that resolves to 127.0.0.1
        self.assertEqual(self.req("GET", "/api/state", headers={"Host": f"evil.example:{self.port}"})[0], 403)
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.req("POST", "/api/stop", body={}, headers={"Origin": "https://evil.example"})[0], 403)
        status, _, _ = self.req("POST", "/api/stop", headers={"Content-Type": "text/plain"})
        self.assertEqual(status, 415)
        self.assertEqual(self.req("GET", "/runs/../../etc/passwd")[0], 404)
        self.assertEqual(self.req("GET", "/api/state")[0], 200)

    # -- keys --
    def test_keys_are_saved_but_never_sent_back(self):
        os.environ.pop("KARAMANIYA_GUI_TEST_KEY", None)
        env_path = os.path.join(self.tmp, ".env")
        status, d = self.api("POST", "keys", {"name": "KARAMANIYA_GUI_TEST_KEY", "value": SECRET,
                                               "names": ["KARAMANIYA_GUI_TEST_KEY"]})
        self.assertEqual(status, 200)
        self.assertNotIn(SECRET, json.dumps(d))
        row = [k for k in d["keys"] if k["name"] == "KARAMANIYA_GUI_TEST_KEY"][0]
        self.assertEqual(row["source"], ".env")
        self.assertTrue(os.environ.get("KARAMANIYA_GUI_TEST_KEY") == SECRET, "the saved key did not reach the environment")
        with open(env_path, encoding="utf-8") as f:
            self.assertIn(f"KARAMANIYA_GUI_TEST_KEY={SECRET}", f.read())
        for name in ("state", "live", "runs", "compare"):
            _, _, raw = self.req("GET", "/api/" + name)
            self.assertNotIn(SECRET, raw.decode())
        _, _, raw = self.req("GET", "/api/keys?names=KARAMANIYA_GUI_TEST_KEY")
        self.assertNotIn(SECRET, raw.decode())
        self.assertEqual(self.api("POST", "keys", {"name": "bad name", "value": "x"})[0], 400)
        self.assertEqual(self.api("POST", "keys", {"name": "KARAMANIYA_GUI_TEST_KEY", "value": "a\nb"})[0], 400)
        status, d = self.api("POST", "keys", {"name": "KARAMANIYA_GUI_TEST_KEY", "value": ""})
        self.assertEqual(status, 200)
        self.assertNotIn("KARAMANIYA_GUI_TEST_KEY", envfile.read_env(env_path))
        self.assertFalse("KARAMANIYA_GUI_TEST_KEY" in os.environ, "the removed key is still in the environment")

    # -- council files --
    def test_council_files(self):
        cfg = self.scripted_config(3)
        status, d = self.api("POST", "config", {"name": "council.scripted.toml", "config": cfg})
        self.assertEqual(status, 400)  # shipped examples are read-only
        self.assertEqual(self.api("POST", "config", {"name": "../evil.toml", "config": cfg})[0], 400)
        cfg["seats"][0]["label"] = "my-democrat"
        status, d = self.api("POST", "config", {"name": "council.test.toml", "config": cfg})
        self.assertEqual(status, 200)
        status, back = self.api("GET", "config", name="council.test.toml")
        self.assertEqual(status, 200)
        self.assertEqual([s["label"] for s in back["config"]["seats"]], [s["label"] for s in cfg["seats"]])
        self.assertEqual(back["config"]["run"]["months"], 3)
        bad = {"run": cfg["run"], "seats": [cfg["seats"][0], dict(cfg["seats"][0])]}
        status, d = self.api("POST", "config", {"name": "council.bad.toml", "config": bad})
        self.assertEqual(status, 400)
        self.assertIn("unique", d["error"])

    # -- a run, start to finish, then stop and resume --
    def test_run_stop_resume(self):
        cfg = self.scripted_config(2)
        status, job = self.api("POST", "run", {"config": cfg, "name": "gui-one"})
        self.assertEqual(status, 200, job)
        live = self.wait_idle()
        job = live["job"]
        self.assertEqual(job["status"], "finished", job)
        self.assertEqual(job["months_done"], 2)
        kinds = {i["kind"] for i in live["items"]}
        self.assertTrue({"started", "month", "statement", "resolved", "month_done", "finished"} <= kinds, kinds)
        status, headers, raw = self.req("GET", "/runs/gui-one/report.html", token=None)
        self.assertEqual(status, 200)
        self.assertIn("Last-Modified", headers)
        self.assertEqual(self.req("GET", "/runs/gui-one/checkpoint.json")[0], 404)  # not served
        status, runs = self.api("GET", "runs")
        row = [r for r in runs["runs"] if r["id"] == "gui-one"][0]
        self.assertEqual((row["status"], row["months_done"]), ("finished", 2))
        status, cmp_ = self.api("GET", "compare")
        self.assertEqual(len(cmp_["models"]), 5)
        status, world = self.api("GET", "world", run="gui-one", since=0)
        self.assertEqual(status, 200)
        self.assertTrue(world["ready"] and world["geo"]["regions"] and len(world["rows"]) == 2)
        self.assertIn("region_detail", world["rows"][0])
        status, more = self.api("GET", "world", run="gui-one", since=1)
        self.assertEqual((len(more["rows"]), "geo" in more), (1, False))  # later calls send only new months
        self.assertEqual(self.api("GET", "world", run="nope", since=0)[0], 404)
        status, idx = self.api("GET", "inspect", run="gui-one")
        self.assertEqual(status, 200)
        self.assertTrue(idx["system_exact"])  # the run saved its own standing instructions
        status, month = self.api("GET", "inspect", run="gui-one", month=0)
        # Version 2: opening, response-and-revision round, final decisions (five seats each).
        self.assertEqual(len(month["calls"]), 15)
        self.assertEqual({c["phase"] for c in month["calls"]}, {"session", "revision", "decision"})
        self.assertTrue(all(c["prompt"] for c in month["calls"]))
        self.assertEqual(self.api("POST", "run", {"config": cfg, "name": "gui-one"})[0], 409)  # name taken

        cfg = self.scripted_config(6)
        status, job = self.api("POST", "run", {"config": cfg, "name": "gui-two"})
        self.assertEqual(status, 200, job)
        self.assertEqual(self.api("POST", "run", {"config": cfg, "name": "gui-three"})[0], 409)  # busy
        self.assertEqual(self.api("POST", "stop", {})[0], 200)
        live = self.wait_idle()
        self.assertEqual(live["job"]["status"], "stopped", live["job"])
        done = live["job"]["months_done"]
        self.assertLess(done, 6)
        status, runs = self.api("GET", "runs")
        self.assertEqual([r for r in runs["runs"] if r["id"] == "gui-two"][0]["status"], "stopped")
        status, job = self.api("POST", "resume", {"run_id": "gui-two"})
        self.assertEqual(status, 200, job)
        live = self.wait_idle()
        self.assertIn(live["job"]["status"], ("finished",), live["job"])
        self.assertEqual(self.api("POST", "resume", {"run_id": "gui-two"})[0], 409)  # finished
        self.assertEqual(self.api("POST", "resume", {"run_id": "nope"})[0], 404)


if __name__ == "__main__":
    unittest.main()
