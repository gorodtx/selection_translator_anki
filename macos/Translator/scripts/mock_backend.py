#!/usr/bin/env python3
"""Stand-in for the Python backend, for developing the macOS shell on its own.

Speaks the same Unix-socket NDJSON protocol as
``desktop_app/platform/macos/ipc/protocol.py``: requests carry id/method/params, responses
echo the id, events carry event/payload. Answers are canned, but the shapes and the
two-phase translation timing (partial, then final) match the real daemon.

    python3 scripts/mock_backend.py [--socket PATH] [--fail-anki]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path

PROTOCOL_VERSION = 1
BACKEND_VERSION = "mock-0.3.0"

TRANSLATIONS: dict[str, dict[str, object]] = {
    "bank": {
        "translation": "берег; банк; насыпь",
        "definitions": [
            "the land alongside a river or lake",
            "a financial establishment that keeps money for customers",
        ],
        "examples": ["We sat on the river bank.", "She works at a bank downtown."],
        "apple": {
            "headword": "bank",
            "ipa_uk": "baŋk",
            "ipa_us": "bæŋk",
            "entries": [
                {
                    "pos": "noun",
                    "senses": [
                        {
                            "index": 1,
                            "label": "of river",
                            "translation": "бе́рег",
                            "examples": [{"en": "bank of clouds", "ru": "гряда́ облако́в"}],
                        },
                        {"index": 2, "label": "Finance", "translation": "банк", "examples": []},
                    ],
                },
                {
                    "pos": "transitive verb",
                    "senses": [
                        {
                            "index": 1,
                            "label": "put into bank",
                            "translation": "класть (impf) в банк / положи́ть (pf) в банк",
                            "examples": [],
                        }
                    ],
                },
            ],
        },
    },
    "look up": {
        "translation": "навестить; отыскать; улучшаться",
        "definitions": ["to search for information in a reference work"],
        "examples": ["Look up the word in a dictionary.", "Things are looking up."],
        "apple": {
            "headword": "look up",
            "ipa_uk": "lʊk",
            "ipa_us": "lʊk",
            "entries": [
                {
                    "pos": "transitive verb",
                    "senses": [
                        {
                            "index": 1,
                            "label": "visit",
                            "translation": "навеща́ть (impf) / навести́ть (pf)",
                            "examples": [{"en": "look up trains", "ru": "посмотре́ть расписа́ние"}],
                        }
                    ],
                }
            ],
        },
    },
}
DEFAULT = {
    "translation": "перевод недоступен в моке",
    "definitions": [],
    "examples": [],
    "apple": None,
}


def view_state(text: str, *, loading: bool, final: bool, entry_id: int | None) -> dict[str, object]:
    data = TRANSLATIONS.get(text.strip().lower(), DEFAULT)
    return {
        "original": text.strip(),
        "original_raw": text,
        "translation": data["translation"] if not loading or final else "",
        "definitions_items": list(data["definitions"]) if final else [],
        "examples": [{"en": item} for item in data["examples"]] if final else [],
        "can_refresh_examples": final and bool(data["examples"]),
        "refreshing_examples": False,
        "loading": loading,
        "can_add_anki": final,
        "entry_id": entry_id,
        **({"apple": data["apple"]} if final and data["apple"] else {}),
    }


class Backend:
    """Session state shared by every connection (the real daemon is single-session too)."""

    def __init__(self, *, fail_anki: bool) -> None:
        self.fail_anki = fail_anki
        self.request_id = 0
        self.entry_id = 0
        self.current = ""
        self.history: list[dict[str, object]] = []
        self.deck = "Vocabulary"
        self.clients: list[socket.socket] = []
        self.lock = threading.Lock()

    # -- events -------------------------------------------------------------

    def broadcast(self, event: str, payload: dict[str, object]) -> None:
        line = (json.dumps({"event": event, "payload": payload}, ensure_ascii=False) + "\n").encode()
        with self.lock:
            targets = list(self.clients)
        for client in targets:
            try:
                client.sendall(line)
            except OSError:
                pass

    def emit_translation(self, phase: str, state: dict[str, object]) -> None:
        self.broadcast(
            "translation.state",
            {"request_id": self.request_id, "phase": phase, "state": state},
        )

    # -- methods ------------------------------------------------------------

    def handle(self, method: str, params: dict[str, object]) -> dict[str, object]:
        handler = getattr(self, f"do_{method.replace('.', '_')}", None)
        if handler is None:
            raise KeyError(method)
        return handler(params)

    def do_ping(self, _: dict[str, object]) -> dict[str, object]:
        return {
            "version": BACKEND_VERSION,
            "protocol": PROTOCOL_VERSION,
            "pid": os.getpid(),
            "platform": "darwin",
            "db": {
                "primary": True,
                "fallback": True,
                "definitions": False,
                "dir": str(Path.home() / "Library/Application Support/Translator/db"),
            },
            "engines": {"apple_dictionary": True, "apple_translation": False},
        }

    def do_translate(self, params: dict[str, object]) -> dict[str, object]:
        text = str(params.get("text", ""))
        self.request_id += 1
        self.entry_id += 1
        self.current = text
        state = view_state(text, loading=True, final=False, entry_id=self.entry_id)
        threading.Thread(target=self._finish_translation, args=(text, self.entry_id), daemon=True).start()
        return {"request_id": self.request_id, "state": state}

    def _finish_translation(self, text: str, entry_id: int) -> None:
        time.sleep(0.15)
        partial = view_state(text, loading=True, final=False, entry_id=entry_id)
        partial["translation"] = TRANSLATIONS.get(text.strip().lower(), DEFAULT)["translation"]
        self.emit_translation("partial", partial)
        time.sleep(0.5)
        final = view_state(text, loading=False, final=True, entry_id=entry_id)
        self.emit_translation("final", final)
        self.history.insert(
            0,
            {
                "entry_id": entry_id,
                "text": text.strip(),
                "lookup_text": text.strip().lower(),
                "translation": final["translation"],
                "definitions_en": final["definitions_items"],
                "examples": [item["en"] for item in final["examples"]],
            },
        )
        self.broadcast("notification", {"message": "Translation ready.", "level": "success"})

    def do_cancel(self, _: dict[str, object]) -> dict[str, object]:
        return {}

    do_close = do_cancel

    def do_history_list(self, _: dict[str, object]) -> dict[str, object]:
        return {"items": self.history}

    def do_history_select(self, params: dict[str, object]) -> dict[str, object]:
        entry_id = int(params.get("entry_id", 0))
        item = next((entry for entry in self.history if entry["entry_id"] == entry_id), None)
        if item is None:
            raise LookupError("no_active_entry")
        self.request_id += 1
        self.current = str(item["text"])
        return {
            "request_id": self.request_id,
            "state": view_state(str(item["text"]), loading=False, final=True, entry_id=entry_id),
        }

    def do_examples_refresh(self, _: dict[str, object]) -> dict[str, object]:
        state = view_state(self.current, loading=False, final=True, entry_id=self.entry_id)
        rotated = list(state["examples"])
        rotated.reverse()
        state["examples"] = rotated
        return {"state": state, "changed": bool(rotated)}

    def do_copy_all(self, _: dict[str, object]) -> dict[str, object]:
        state = view_state(self.current, loading=False, final=True, entry_id=self.entry_id)
        lines = [str(state["original"]), str(state["translation"])]
        lines += [str(item) for item in state["definitions_items"]]
        lines += [str(item["en"]) for item in state["examples"]]
        return {"text": "\n".join(line for line in lines if line)}

    def do_anki_status(self, _: dict[str, object]) -> dict[str, object]:
        available = not self.fail_anki
        return {
            "model_status": "Ready" if available else "Unavailable",
            "deck_status": "Selected" if available else "Unavailable",
            "deck_name": self.deck if available else "",
            "available": available,
        }

    def do_anki_decks(self, _: dict[str, object]) -> dict[str, object]:
        if self.fail_anki:
            return {"decks": [], "error": "AnkiConnect is not reachable."}
        return {"decks": ["Default", "Vocabulary", "English::Verbs"], "error": None}

    def do_anki_select_deck(self, params: dict[str, object]) -> dict[str, object]:
        self.deck = str(params.get("deck", ""))
        return {
            "message": f"Deck set to {self.deck}.",
            "model_status": "Ready",
            "deck_status": "Selected",
            "deck_name": self.deck,
        }

    def do_anki_create_model(self, _: dict[str, object]) -> dict[str, object]:
        return {
            "message": "Model created.",
            "model_status": "Ready",
            "deck_status": "Selected",
            "deck_name": self.deck,
        }

    def do_anki_prepare_upsert(self, _: dict[str, object]) -> dict[str, object]:
        if self.fail_anki:
            raise RuntimeError("AnkiConnect is not reachable.")
        state = view_state(self.current, loading=False, final=True, entry_id=self.entry_id)
        return {
            "preview": {
                "values": {
                    "translations": [t.strip() for t in str(state["translation"]).split(";") if t.strip()],
                    "definitions_en": list(state["definitions_items"]),
                    "examples_en": [str(item["en"]) for item in state["examples"]],
                    "image_path": None,
                },
                "matches": [
                    {
                        "note_id": 1700000000001,
                        "word": str(state["original"]),
                        "translation": "старый перевод",
                        "definitions_en": "old definition",
                        "examples_en": ["old example"],
                        "image": None,
                    }
                ],
                "available_fields": ["Word", "Translation", "Example", "definitions_en", "image"],
            }
        }

    def do_anki_apply_upsert(self, params: dict[str, object]) -> dict[str, object]:
        decision = params.get("decision", {})
        assert isinstance(decision, dict)
        if decision.get("create_new"):
            return {"outcome": "success", "message": "Note added."}
        targets = decision.get("target_note_ids") or []
        return {"outcome": "updated", "message": f"{len(targets)} note(s) updated."}

    def do_settings_get(self, _: dict[str, object]) -> dict[str, object]:
        return {
            "languages": {"source": "en", "target": "ru"},
            "anki": {
                "deck": self.deck,
                "model": "Translator",
                "fields": {
                    "word": "Word",
                    "translation": "Translation",
                    "example_en": "Example",
                    "definitions_en": "definitions_en",
                    "image": "image",
                },
            },
        }

    def do_settings_save(self, params: dict[str, object]) -> dict[str, object]:
        config = params.get("config", {})
        assert isinstance(config, dict)
        anki = config.get("anki", {})
        if isinstance(anki, dict):
            self.deck = str(anki.get("deck", self.deck))
        return {
            "message": "Settings saved.",
            "model_status": "Ready",
            "deck_status": "Selected",
            "deck_name": self.deck,
        }

    def do_shutdown(self, _: dict[str, object]) -> dict[str, object]:
        threading.Timer(0.2, lambda: os._exit(0)).start()
        return {}


class Handler(socketserver.BaseRequestHandler):
    backend: Backend

    def handle(self) -> None:
        client: socket.socket = self.request
        with self.backend.lock:
            self.backend.clients.append(client)
        buffer = b""
        try:
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    return
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._dispatch(client, line)
        except OSError:
            return
        finally:
            with self.backend.lock:
                if client in self.backend.clients:
                    self.backend.clients.remove(client)

    def _dispatch(self, client: socket.socket, line: bytes) -> None:
        try:
            payload = json.loads(line)
            request_id = payload["id"]
            method = payload["method"]
            params = payload.get("params") or {}
        except Exception:
            self._send(client, {"id": None, "ok": False, "error": {"code": "bad_request", "message": "Malformed JSON."}})
            return
        try:
            result = self.backend.handle(method, params)
        except KeyError:
            self._send(client, {"id": request_id, "ok": False, "error": {"code": "unknown_method", "message": method}})
            return
        except LookupError as exc:
            self._send(client, {"id": request_id, "ok": False, "error": {"code": "no_active_entry", "message": str(exc)}})
            return
        except Exception as exc:  # noqa: BLE001 - mock surfaces any failure verbatim
            self._send(client, {"id": request_id, "ok": False, "error": {"code": "anki_error", "message": str(exc)}})
            return
        self._send(client, {"id": request_id, "ok": True, "result": result})

    def _send(self, client: socket.socket, payload: dict[str, object]) -> None:
        try:
            client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        except OSError:
            pass


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_socket = os.environ.get("TRANSLATOR_SOCKET_PATH") or str(
        Path.home() / "Library/Application Support/Translator/run/backend.sock"
    )
    parser.add_argument("--socket", default=default_socket)
    parser.add_argument("--fail-anki", action="store_true", help="report AnkiConnect as unreachable")
    args = parser.parse_args()

    path = Path(args.socket).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    Handler.backend = Backend(fail_anki=args.fail_anki)
    server = Server(str(path), Handler)
    os.chmod(path, 0o600)
    print(f"mock backend listening on {path}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if path.exists():
            path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
