from __future__ import annotations

import argparse
import string
import subprocess
import time
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class KeyStroke:
    keys: tuple[str, ...]


_SHIFT_SYMBOLS: dict[str, str] = {
    "~": "KEY_GRAVE",
    "!": "KEY_1",
    "@": "KEY_2",
    "#": "KEY_3",
    "$": "KEY_4",
    "%": "KEY_5",
    "^": "KEY_6",
    "&": "KEY_7",
    "*": "KEY_8",
    "(": "KEY_9",
    ")": "KEY_0",
    "_": "KEY_MINUS",
    "+": "KEY_EQUAL",
    "{": "KEY_LEFTBRACE",
    "}": "KEY_RIGHTBRACE",
    "|": "KEY_BACKSLASH",
    ":": "KEY_SEMICOLON",
    '"': "KEY_APOSTROPHE",
    "<": "KEY_COMMA",
    ">": "KEY_DOT",
    "?": "KEY_SLASH",
}

_PLAIN_SYMBOLS: dict[str, str] = {
    " ": "KEY_SPACE",
    "-": "KEY_MINUS",
    "=": "KEY_EQUAL",
    "[": "KEY_LEFTBRACE",
    "]": "KEY_RIGHTBRACE",
    "\\": "KEY_BACKSLASH",
    ";": "KEY_SEMICOLON",
    "'": "KEY_APOSTROPHE",
    ",": "KEY_COMMA",
    ".": "KEY_DOT",
    "/": "KEY_SLASH",
    "`": "KEY_GRAVE",
}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Type text into a running VM via virsh send-key."
    )
    parser.add_argument(
        "--connect-uri",
        default="qemu:///system",
        help="Libvirt connection URI.",
    )
    parser.add_argument(
        "--domain",
        default="win11-gate",
        help="Domain name.",
    )
    parser.add_argument(
        "--text",
        required=True,
        help="Text to type into the currently focused guest input field.",
    )
    parser.add_argument(
        "--enter",
        action="store_true",
        help="Press Enter at the end.",
    )
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=40,
        help="Delay between keystrokes.",
    )
    return parser.parse_args(argv)


def _char_to_keystroke(char: str) -> KeyStroke:
    if char in string.ascii_lowercase:
        return KeyStroke((f"KEY_{char.upper()}",))
    if char in string.ascii_uppercase:
        return KeyStroke(("KEY_LEFTSHIFT", f"KEY_{char}"))
    if char in string.digits:
        return KeyStroke((f"KEY_{char}",))
    if char in _PLAIN_SYMBOLS:
        return KeyStroke((_PLAIN_SYMBOLS[char],))
    if char in _SHIFT_SYMBOLS:
        return KeyStroke(("KEY_LEFTSHIFT", _SHIFT_SYMBOLS[char]))
    if char == "\n":
        return KeyStroke(("KEY_ENTER",))
    raise ValueError(f"unsupported character for virsh send-key: {char!r}")


def _run_key(
    *,
    connect_uri: str,
    domain: str,
    keys: Sequence[str],
) -> None:
    completed = subprocess.run(
        [
            "virsh",
            "-c",
            connect_uri,
            "send-key",
            domain,
            *keys,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return
    details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
    raise RuntimeError(f"send-key failed for {keys}: {details}")


def type_text(
    *,
    connect_uri: str,
    domain: str,
    text: str,
    press_enter: bool,
    delay_ms: int,
) -> None:
    delay_sec = max(delay_ms, 0) / 1000.0
    for char in text:
        stroke = _char_to_keystroke(char)
        _run_key(connect_uri=connect_uri, domain=domain, keys=stroke.keys)
        if delay_sec:
            time.sleep(delay_sec)
    if press_enter:
        _run_key(connect_uri=connect_uri, domain=domain, keys=("KEY_ENTER",))


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    type_text(
        connect_uri=args.connect_uri,
        domain=args.domain,
        text=args.text,
        press_enter=args.enter,
        delay_ms=args.delay_ms,
    )
    print(f"Typed {len(args.text)} characters into domain '{args.domain}'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
