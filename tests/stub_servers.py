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
        self.refuse = False
        self.usage = {}             # extra usage fields, e.g. the cache counts a provider reports
        self.thinking = ""          # reasoning to return: a thinking block, Ollama's thinking field
        self.message_extra = {}     # extra chat-completion message fields, e.g. reasoning_content


def _handler(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, payload: dict):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            state.requests.append((self.path, dict(self.headers), body))
            text = json.dumps(state.reply)
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
                fmt = (body.get("response_format") or {}).get("type")
                if state.reject_json_schema and fmt == "json_schema":
                    self._send(400, {"error": {"message": "response_format type json_schema is not supported"}})
                    return
                msg = {"role": "assistant", "content": text, **state.message_extra}
                if state.refuse:
                    msg = {"role": "assistant", "content": None, "refusal": "I can't help with that."}
                self._send(200, {"id": "c1", "model": body.get("model", "?") + "-2026",
                                 "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                                 "usage": {"prompt_tokens": 900, "completion_tokens": 60, **state.usage}})
            elif self.path.endswith("/api/chat"):
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
