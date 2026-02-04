from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final


ROOT: Final[Path] = Path(__file__).resolve().parents[1]
REPORT_DIR: Final[Path] = ROOT / ".problems"
STRICT: Final[bool] = os.getenv("PROBLEMS_STRICT", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


def run(cmd: list[str], *, report_name: str) -> tuple[int, str]:
    """
    Runs command in project root, captures combined stdout+stderr,
    writes raw output to .problems/{report_name}.txt and returns (rc, output).
    """
    p = subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    out = p.stdout or ""
    (REPORT_DIR / f"{report_name}.txt").write_text(out, encoding="utf-8")
    return p.returncode, out


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    overall_failed = False
    sections: list[str] = []

    rc, out = run(["ruff", "format", "--check", "."], report_name="ruff_format_check")
    sections.append("=== ruff format --check ===\n" + out.rstrip() + "\n")
    if rc != 0:
        overall_failed = True

    rc, out_txt = run(["ruff", "check", "."], report_name="ruff_check")
    sections.append("=== ruff check ===\n" + out_txt.rstrip() + "\n")
    if rc != 0:
        overall_failed = True

    _rc_json, out_json = run(
        ["ruff", "check", ".", "--output-format", "json"],
        report_name="ruff_check_json",
    )
    (REPORT_DIR / "ruff.json").write_text(out_json, encoding="utf-8")

    rc, out = run(["ty", "check"], report_name="ty_check")
    sections.append("=== ty check ===\n" + out.rstrip() + "\n")
    if rc != 0:
        overall_failed = True

    combined = "\n".join(sections).strip() + "\n"
    (REPORT_DIR / "problems.txt").write_text(combined, encoding="utf-8")

    print(combined)

    return 1 if overall_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
