from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "windows" / "vm" / "virsh_send_text.py"
    spec = importlib.util.spec_from_file_location("virsh_send_text", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load virsh_send_text module.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_char_to_keystroke_maps_basic_ascii() -> None:
    module = _module()

    assert module._char_to_keystroke("a").keys == ("KEY_A",)
    assert module._char_to_keystroke("A").keys == ("KEY_LEFTSHIFT", "KEY_A")
    assert module._char_to_keystroke("7").keys == ("KEY_7",)
    assert module._char_to_keystroke("-").keys == ("KEY_MINUS",)
    assert module._char_to_keystroke(":").keys == ("KEY_LEFTSHIFT", "KEY_SEMICOLON")
    assert module._char_to_keystroke("\\").keys == ("KEY_BACKSLASH",)


def test_char_to_keystroke_rejects_unsupported_chars() -> None:
    module = _module()
    try:
        module._char_to_keystroke("й")
        raise AssertionError("Expected ValueError for unsupported character.")
    except ValueError:
        pass
