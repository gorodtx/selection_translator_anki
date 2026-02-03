from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Final, TypedDict, cast


class PyrightSummary(TypedDict, total=False):
    errorCount: int
    warningCount: int
    informationCount: int


class PyrightOutput(TypedDict, total=False):
    summary: PyrightSummary


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

    rc, out = run(["mypy"], report_name="mypy")
    sections.append("=== mypy ===\n" + out.rstrip() + "\n")
    if rc != 0:
        overall_failed = True

    rc, out_text = run(["pyright"], report_name="pyright")
    sections.append("=== pyright ===\n" + out_text.rstrip() + "\n")
    if rc != 0:
        overall_failed = True

    _rc_json, out_json_text = run(
        ["pyright", "--outputjson"], report_name="pyright_outputjson"
    )
    (REPORT_DIR / "pyright.json").write_text(out_json_text, encoding="utf-8")

    if STRICT:
        try:
            parsed = cast(PyrightOutput, json.loads(out_json_text or "{}"))
            summary = parsed.get("summary", {})
            errors = int(summary.get("errorCount", 0) or 0)
            warnings = int(summary.get("warningCount", 0) or 0)
            infos = int(summary.get("informationCount", 0) or 0)

            (REPORT_DIR / "pyright_summary.txt").write_text(
                f"errors={errors} warnings={warnings} infos={infos}\n",
                encoding="utf-8",
            )

            if errors or warnings:
                overall_failed = True

        except Exception as e:
            (REPORT_DIR / "pyright_summary.txt").write_text(
                f"Failed to parse pyright json: {e}\n",
                encoding="utf-8",
            )
            overall_failed = True

    combined = "\n".join(sections).strip() + "\n"
    (REPORT_DIR / "problems.txt").write_text(combined, encoding="utf-8")

    print(combined)

    return 1 if overall_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
