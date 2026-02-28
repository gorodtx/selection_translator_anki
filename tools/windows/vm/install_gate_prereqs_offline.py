from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import time
from typing import Sequence


DEFAULT_STEPS: tuple[tuple[str, int], ...] = (
    (
        "for %d in (D E F G H I J K L M N O P) do @if exist %d:\\GoogleChromeStandaloneEnterprise64.msi set PAYLOAD=%d:",
        1,
    ),
    ("echo PAYLOAD=%PAYLOAD%", 1),
    ('msiexec /i "%PAYLOAD%\\GoogleChromeStandaloneEnterprise64.msi" /qn /norestart', 18),
    ('"%PAYLOAD%\\vc_redist.x64.exe" /install /quiet /norestart', 16),
    ('start /wait "" "%PAYLOAD%\\anki-25.02.7-windows-qt6.exe" /S', 55),
    ('mkdir "%APPDATA%\\Anki2\\addons21\\2055492159"', 1),
    (
        'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath \'%PAYLOAD%\\anki-connect-master.zip\' -DestinationPath \'$env:TEMP\\anki-connect\' -Force"',
        4,
    ),
    (
        'xcopy /E /I /Y "%TEMP%\\anki-connect\\anki-connect-master\\plugin" "%APPDATA%\\Anki2\\addons21\\2055492159"',
        3,
    ),
    ('if exist "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" echo CHROME_OK', 1),
    ('if exist "%LOCALAPPDATA%\\Programs\\Anki\\anki.exe" echo ANKI_OK', 1),
    ('if exist "%APPDATA%\\Anki2\\addons21\\2055492159\\__init__.py" echo ANKICONNECT_OK', 1),
    (
        'reg query "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Installed',
        1,
    ),
    (
        'reg query "HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\x64" /v Version',
        1,
    ),
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Install Windows gate prerequisites from attached payload ISO in a focused "
            "admin cmd.exe session."
        )
    )
    parser.add_argument("--connect-uri", default="qemu:///system", help="Libvirt URI.")
    parser.add_argument("--domain", default="win11-gate", help="Libvirt domain name.")
    parser.add_argument(
        "--delay-ms",
        type=int,
        default=6,
        help="Delay between sent keystrokes.",
    )
    parser.add_argument(
        "--open-cmd",
        action="store_true",
        help="Try to open admin cmd.exe first via Win+R (requires GUI focus).",
    )
    parser.add_argument(
        "--capture-dir",
        type=Path,
        default=None,
        help="Optional directory for VNC screenshots after key milestones.",
    )
    parser.add_argument(
        "--vnc-server",
        default="127.0.0.1::5900",
        help="vncdo server argument.",
    )
    return parser.parse_args(argv)


def _run(command: Sequence[str], *, action: str) -> None:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 0:
        return
    details = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
    raise RuntimeError(f"{action} failed: {details}")


def _send_key(connect_uri: str, domain: str, *keys: str) -> None:
    _run(
        ["virsh", "-c", connect_uri, "send-key", domain, *keys],
        action=f"send-key {' '.join(keys)}",
    )


def _send_text(
    *,
    repo_root: Path,
    connect_uri: str,
    domain: str,
    text: str,
    delay_ms: int,
    enter: bool = True,
) -> None:
    tool = repo_root / "tools" / "windows" / "vm" / "virsh_send_text.py"
    command = [
        "python",
        str(tool),
        "--connect-uri",
        connect_uri,
        "--domain",
        domain,
        "--text",
        text,
        "--delay-ms",
        str(delay_ms),
    ]
    if enter:
        command.append("--enter")
    _run(command, action=f"type text: {text[:60]}")


def _capture(vnc_server: str, capture_dir: Path, label: str) -> Path:
    capture_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    path = capture_dir / f"{label}-{stamp}.png"
    _run(["vncdo", "-s", vnc_server, "capture", str(path)], action="capture screenshot")
    return path


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[3]

    if args.open_cmd:
        _send_key(args.connect_uri, args.domain, "KEY_LEFTMETA", "KEY_R")
        time.sleep(1)
        # Toggle layout once; caller should keep guest at ENG beforehand.
        _send_key(args.connect_uri, args.domain, "KEY_LEFTALT", "KEY_LEFTSHIFT")
        time.sleep(0.4)
        _send_key(args.connect_uri, args.domain, "KEY_LEFTCTRL", "KEY_A")
        time.sleep(0.2)
        _send_key(args.connect_uri, args.domain, "KEY_BACKSPACE")
        time.sleep(0.2)
        _send_text(
            repo_root=repo_root,
            connect_uri=args.connect_uri,
            domain=args.domain,
            text="cmd",
            delay_ms=args.delay_ms,
            enter=True,
        )
        time.sleep(2)

    captures: list[Path] = []
    for index, (command, wait_sec) in enumerate(DEFAULT_STEPS, start=1):
        _send_text(
            repo_root=repo_root,
            connect_uri=args.connect_uri,
            domain=args.domain,
            text=command,
            delay_ms=args.delay_ms,
            enter=True,
        )
        if wait_sec > 0:
            time.sleep(wait_sec)

        if args.capture_dir is None:
            continue
        if index in {2, 5, 8, len(DEFAULT_STEPS)}:
            captures.append(_capture(args.vnc_server, args.capture_dir, f"prereq-step-{index:02d}"))

    print("Offline prerequisite install sequence finished.")
    if captures:
        print("Captured screenshots:")
        for item in captures:
            print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
