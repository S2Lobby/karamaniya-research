"""Tiny fake API servers, so the connectors can be tested without keys or network."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubState:
    def __init__(self):
        self.requests = []          # (path, headers, body)
        self.reply = {"ok": True, "note": "ready"}
        self.reject_json_schema = False
        self.schema_reject_message = "response_format type json_schema is not supported"
        self.schema_error_in_200 = False   # OpenRouter style: HTTP 200 carrying an error object inside
        self.systemone_status = 200        # the fake TypeSafe endpoint: raise to test error handling
        self.systemone_error = "invalid questions"
        self.last_path = ""                # the last System One/OpenRouter request path and Authorization header
        self.last_auth = ""
        self.systemone_reply = {           # a valid answer set for the default judge panel
            "survive_to_end": {"type": "choice", "choice": "no",
                               "probabilities": {"yes": 0.3, "no": 0.7}, "confidence": 0.4},
            "how_ends": {"type": "choice", "choice": "collapse_or_force",
                         "probabilities": {"handover_on_time": 0.2, "collapse_or_force": 0.6, "other": 0.2},
                         "confidence": 0.35},
            "crisis_severity": {"type": "score", "score": 2.9,
                                "legend": {"0": "calm", "4": "collapsing"},
                                "probabilities": {"2": 0.3, "3": 0.6}, "confidence": 0.3},
            "enough_evidence": {"type": "noul", "noul": 0.8},
        }
        self.refuse = False
        self.usage = {}             # extra usage fields, e.g. the cache counts a provider reports
        self.thinking = ""          # reasoning to return: a thinking block, Ollama's thinking field
        self.message_extra = {}     # extra chat-completion message fields, e.g. reasoning_content
        self.text_override = None   # send this as the answer text verbatim, not json.dumps(state.reply)
        self.raw_body = None        # send this as the whole reply body verbatim (a broken provider)


def _handler(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, payload: dict):
            self._send_raw(code, json.dumps(payload))

        def _send_raw(self, code: int, text: str):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            state.requests.append((self.path, dict(self.headers), body))
            text = state.text_override if state.text_override is not None else json.dumps(state.reply)
            if self.path.endswith("/v1/systemone") or self.path.endswith("/api/alpha/decisions"):
                state.last_path = self.path
                state.last_auth = self.headers.get("Authorization", "")
                if state.systemone_status != 200:
                    self._send(state.systemone_status, {"error": {"message": state.systemone_error}})
                    return
                self._send(200, {"model": "jev-stub-1", "answers": state.systemone_reply,
                                 "usage": {"input_tokens": 5000, "output_tokens": 40}})
                return
            if self.path.endswith("/v1/messages"):
                if state.refuse:
                    content, stop = [], "refusal"
                else:
                    content, stop = [{"type": "text", "text": text}], "end_turn"
                    if state.thinking:
                        content.insert(0, {"type": "thinking", "thinking": state.thinking, "signature": "sig"})
                self._send(200, {"id": "msg_test", "type": "message", "role": "assistant",
                                 "model": body.get("model", "?"), "content": content,
                                 "stop_reason": stop, "stop_sequence": None,
                                 "usage": {"input_tokens": 1200, "output_tokens": 80,
                                           "cache_read_input_tokens": 0,
                                           "cache_creation_input_tokens": 0, **state.usage}})
            elif self.path.endswith("/chat/completions"):
                if state.raw_body is not None:
                    self._send_raw(200, state.raw_body)
                    return
                fmt = (body.get("response_format") or {}).get("type")
                if state.reject_json_schema and fmt == "json_schema":
                    if state.schema_error_in_200:
                        self._send(200, {"error": {"message": state.schema_reject_message, "code": 400}})
                    else:
                        self._send(400, {"error": {"message": state.schema_reject_message}})
                    return
                msg = {"role": "assistant", "content": text, **state.message_extra}
                if state.refuse:
                    msg = {"role": "assistant", "content": None, "refusal": "I can't help with that."}
                self._send(200, {"id": "c1", "model": body.get("model", "?") + "-2026",
                                 "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 900, "completion_tokens": 60, **state.usage}})
            elif self.path.endswith("/api/chat"):
                if state.raw_body is not None:
                    self._send_raw(200, state.raw_body)
                    return
                message = {"role": "assistant", "content": text}
                if state.thinking:
                    message["thinking"] = state.thinking
                self._send(200, {"model": body.get("model", "?"), "done": True,
                                 "message": message,
                                 "prompt_eval_count": 800, "eval_count": 50})
            else:
                self._send(404, {"error": "not found"})

    return Handler


def start() -> tuple:
    state = StubState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state, f"http://127.0.0.1:{server.server_address[1]}"
