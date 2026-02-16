from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from nightly_dataset import golden_queries

from desktop_app.services.history import HistoryStore
from desktop_app.services.result_cache import ResultCache
from translate_logic.application.translate import translate_async
from translate_logic.models import FieldValue, TranslationResult

BUS_NAME = "com.translator.desktop"
OBJECT_PATH = "/com/translator/desktop"
INTERFACE_NAME = "com.translator.desktop"
SERVICE_NAME = "translator-desktop.service"

STRICT_LATENCY_LIMITS = {
    "p50_ms": 500.0,
    "p95_ms": 2500.0,
    "p99_ms": 5000.0,
    "max_ms": 8000.0,
}
STRICT_CPU_LIMIT_PERCENT = 85.0

NON_NETWORK_TIMEOUT_PATTERNS: tuple[str, ...] = (
    r"join\(timeout=",
    r"result\(timeout=",
    r"wait\(timeout=",
    r"GLib\.timeout_add",
    r"set_timeout\(",
)
_NON_NETWORK_TIMEOUT_ALLOWLIST: tuple[str, ...] = (
    "desktop_app/gtk_types.py",
    "desktop_app/notifications/banner.py",
    "gnome_extension/translator@com.translator.desktop/extension.js",
)


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="seconds")


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * percent))
    return ordered[index]


def _run_command(cmd: list[str], *, timeout_s: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_s,
    )


def _parse_systemctl_show(output: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _to_int(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _wait_for_dbus_ready(max_attempts: int = 50) -> bool:
    for _ in range(max_attempts):
        proc = _run_command(
            [
                "gdbus",
                "introspect",
                "--session",
                "--dest",
                BUS_NAME,
                "--object-path",
                OBJECT_PATH,
            ]
        )
        if proc.returncode == 0 and f"interface {INTERFACE_NAME}" in proc.stdout:
            return True
        time.sleep(0.2)
    return False


def _dbus_call(method: str, arg: str | None = None) -> tuple[bool, float, str]:
    cmd = [
        "gdbus",
        "call",
        "--session",
        "--dest",
        BUS_NAME,
        "--object-path",
        OBJECT_PATH,
        "--method",
        f"{INTERFACE_NAME}.{method}",
    ]
    if arg is not None:
        cmd.append(arg)
    started = time.perf_counter()
    proc = _run_command(cmd)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    output = (proc.stdout or proc.stderr).strip()
    return proc.returncode == 0, elapsed_ms, output


def _systemctl_metrics() -> dict[str, int]:
    proc = _run_command(
        [
            "systemctl",
            "--user",
            "show",
            SERVICE_NAME,
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "NRestarts",
            "-p",
            "MainPID",
            "-p",
            "MemoryCurrent",
            "-p",
            "MemoryPeak",
        ]
    )
    parsed = _parse_systemctl_show(proc.stdout)
    return {
        "active": 1 if parsed.get("ActiveState") == "active" else 0,
        "running": 1 if parsed.get("SubState") == "running" else 0,
        "n_restarts": _to_int(parsed.get("NRestarts")),
        "main_pid": _to_int(parsed.get("MainPID")),
        "memory_current": _to_int(parsed.get("MemoryCurrent")),
        "memory_peak": _to_int(parsed.get("MemoryPeak")),
    }


def _cpu_percent(pid: int) -> float:
    if pid <= 0:
        return 0.0
    proc = _run_command(["ps", "-p", str(pid), "-o", "%cpu="])
    if proc.returncode != 0:
        return 0.0
    value = proc.stdout.strip()
    try:
        return float(value)
    except ValueError:
        return 0.0


def _static_guard_scan() -> list[dict[str, str]]:
    violations: list[dict[str, str]] = []
    for pattern in NON_NETWORK_TIMEOUT_PATTERNS:
        proc = _run_command(
            [
                "rg",
                "-n",
                "--hidden",
                "-S",
                pattern,
                "desktop_app",
                "translate_logic",
                "gnome_extension",
                "-g",
                "!**/__pycache__/**",
            ]
        )
        if proc.returncode not in (0, 1):
            violations.append(
                {
                    "pattern": pattern,
                    "location": "rg execution failed",
                    "line": proc.stderr.strip(),
                }
            )
            continue
        if proc.returncode == 1:
            continue
        for row in proc.stdout.splitlines():
            location, _, line = row.partition(":")
            if any(allowed in location for allowed in _NON_NETWORK_TIMEOUT_ALLOWLIST):
                continue
            violations.append({"pattern": pattern, "location": location, "line": row})
    return violations


def _cache_history_correctness_check() -> dict[str, Any]:
    result = TranslationResult(
        translation_ru=FieldValue.present("ok"),
        definitions_en=(),
        examples=(),
    )
    cache = ResultCache()
    history = HistoryStore(max_entries=100)
    for index in range(125):
        key = f"k{index}"
        cache.set(key, result)
        history.add(key, result)

    cache_keys = list(cache._items.keys())  # noqa: SLF001
    history_items = list(history._items)  # noqa: SLF001
    cache_ok = (
        len(cache_keys) == 100
        and cache_keys[0] == "k25"
        and cache_keys[-1] == "k124"
    )
    history_ok = (
        len(history_items) == 100
        and history_items[0].text == "k25"
        and history_items[-1].text == "k124"
    )

    ttl_absent_cache = not hasattr(cache, "ttl_seconds")
    ttl_absent_history = not hasattr(history, "ttl_seconds")

    probe = ResultCache()
    probe.set("persist", result)
    time.sleep(0.05)
    survives = probe.get("persist") is not None

    return {
        "cache_ok": cache_ok,
        "history_ok": history_ok,
        "ttl_absent_cache": ttl_absent_cache,
        "ttl_absent_history": ttl_absent_history,
        "survives_short_wait": survives,
    }


async def _provider_quality_run() -> dict[str, Any]:
    queries = golden_queries()
    latencies: list[float] = []
    success = 0
    empty = 0
    variants_violation = 0
    rows: list[dict[str, Any]] = []

    for item in queries:
        started = time.perf_counter()
        result = await translate_async(item.text, "en", "ru")
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        latencies.append(elapsed_ms)

        translation = result.translation_ru.text.strip()
        variants = [value.strip() for value in translation.split(";") if value.strip()]
        is_success = result.status.value == "success" and bool(translation)
        if is_success:
            success += 1
        else:
            empty += 1
        if len(variants) > 8:
            variants_violation += 1
        rows.append(
            {
                "text": item.text,
                "kind": item.kind,
                "status": result.status.value,
                "translation": translation,
                "variants_count": len(variants),
                "latency_ms": elapsed_ms,
            }
        )

    consistency_checks = 0
    consistency_matches = 0
    for item in queries[:10]:
        first = await translate_async(item.text, "en", "ru")
        second = await translate_async(item.text, "en", "ru")
        consistency_checks += 1
        if first.translation_ru.text == second.translation_ru.text:
            consistency_matches += 1

    total = len(queries)
    return {
        "total": total,
        "success": success,
        "empty": empty,
        "success_rate": (success / total) if total else 0.0,
        "empty_rate": (empty / total) if total else 0.0,
        "p50_ms": _percentile(latencies, 0.50),
        "p95_ms": _percentile(latencies, 0.95),
        "p99_ms": _percentile(latencies, 0.99),
        "max_ms": max(latencies) if latencies else 0.0,
        "variants_violations": variants_violation,
        "consistency_rate": (
            consistency_matches / consistency_checks if consistency_checks else 0.0
        ),
        "rows": rows,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def _build_report(summary: dict[str, Any]) -> str:
    gate = summary["gate"]
    soak = summary["soak"]
    quality = summary["quality"]
    cache = summary["cache"]
    lines = [
        "# Nightly Quality Report",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- started_at: `{summary['started_at']}`",
        f"- finished_at: `{summary['finished_at']}`",
        f"- status: `{gate['status']}`",
        "",
        "## Soak",
        f"- fail_calls: `{soak['fail_calls']}`",
        f"- n_restarts_max: `{soak['n_restarts_max']}`",
        f"- memory_growth_pct: `{soak['memory_growth_pct']:.2f}`",
        f"- cpu_p95_percent: `{soak['cpu_p95_percent']:.1f}`",
        f"- cpu_max_percent: `{soak['cpu_max_percent']:.1f}`",
        f"- translate_p95_ms: `{soak['translate_p95_ms']:.1f}`",
        "",
        "## Quality",
        f"- success_rate: `{quality['success_rate']:.4f}`",
        f"- empty_rate: `{quality['empty_rate']:.4f}`",
        f"- p50/p95/p99/max: `{quality['p50_ms']:.1f}` / `{quality['p95_ms']:.1f}` / `{quality['p99_ms']:.1f}` / `{quality['max_ms']:.1f}`",
        f"- variants_violations(>8): `{quality['variants_violations']}`",
        f"- consistency_rate: `{quality['consistency_rate']:.4f}`",
        "",
        "## Cache/History",
        f"- cache_ok: `{cache['cache_ok']}`",
        f"- history_ok: `{cache['history_ok']}`",
        f"- ttl_absent_cache/history: `{cache['ttl_absent_cache']}` / `{cache['ttl_absent_history']}`",
        f"- survives_short_wait: `{cache['survives_short_wait']}`",
        "",
        "## Static Guard",
        f"- violations: `{summary['static_guard']['violations_count']}`",
        "",
        "## Gate Reasons",
    ]
    if gate["reasons"]:
        for reason in gate["reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Nightly quality soak and guard runner.")
    parser.add_argument("--duration-hours", type=float, default=8.0)
    parser.add_argument("--interval-sec", type=float, default=10.0)
    parser.add_argument("--burst-every-sec", type=float, default=300.0)
    parser.add_argument("--burst-size", type=int, default=80)
    parser.add_argument("--memory-sample-sec", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--skip-reload", action="store_true")
    args = parser.parse_args()

    run_id = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    output_dir = args.output_dir or Path("dev/tmp/nightly") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    events_path = output_dir / "events.jsonl"
    summary_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"

    started_at = _now_iso()
    random.seed(run_id)

    if not args.skip_reload:
        _run_command(["dev/tools/dev_reload.sh"])
    _run_command(["systemctl", "--user", "start", SERVICE_NAME])

    ready = _wait_for_dbus_ready()
    _append_event(events_path, {"ts": _now_iso(), "event": "dbus_ready", "ready": ready})
    if not ready:
        summary = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": _now_iso(),
            "gate": {"status": "failed", "reasons": ["dbus interface not ready"]},
        }
        _write_json(summary_path, summary)
        report_path.write_text("# Nightly Quality Report\n\n- status: `failed`\n- reason: `dbus interface not ready`\n", encoding="utf-8")
        return 1

    soak_end = time.monotonic() + max(1.0, args.duration_hours * 3600.0)
    next_burst = time.monotonic()
    next_memory = time.monotonic()
    next_static_guard = time.monotonic()

    queries = [item.text for item in golden_queries()]
    translate_latencies: list[float] = []
    fail_calls = 0
    restart_samples: list[int] = []
    memory_samples: list[int] = []
    cpu_samples: list[float] = []
    static_guard_violations: list[dict[str, str]] = []

    while time.monotonic() < soak_end:
        query = random.choice(queries)
        for method, arg in (
            ("Translate", query),
            ("ShowHistory", None),
            ("ShowSettings", None),
            ("GetAnkiStatus", None),
        ):
            ok, elapsed_ms, output = _dbus_call(method, arg)
            _append_event(
                events_path,
                {
                    "ts": _now_iso(),
                    "event": "dbus_call",
                    "method": method,
                    "ok": ok,
                    "elapsed_ms": elapsed_ms,
                    "query": arg,
                    "output": output,
                },
            )
            if method == "Translate":
                translate_latencies.append(elapsed_ms)
            if not ok:
                fail_calls += 1

        now = time.monotonic()
        if now >= next_burst:
            for _ in range(max(1, args.burst_size)):
                query = random.choice(queries)
                ok, elapsed_ms, output = _dbus_call("Translate", query)
                _append_event(
                    events_path,
                    {
                        "ts": _now_iso(),
                        "event": "burst_translate",
                        "ok": ok,
                        "elapsed_ms": elapsed_ms,
                        "query": query,
                        "output": output,
                    },
                )
                translate_latencies.append(elapsed_ms)
                if not ok:
                    fail_calls += 1
            next_burst = now + max(1.0, args.burst_every_sec)

        if now >= next_memory:
            metrics = _systemctl_metrics()
            cpu_percent = _cpu_percent(metrics["main_pid"])
            restart_samples.append(metrics["n_restarts"])
            memory_samples.append(metrics["memory_current"])
            cpu_samples.append(cpu_percent)
            _append_event(
                events_path,
                {
                    "ts": _now_iso(),
                    "event": "service_metrics",
                    "cpu_percent": cpu_percent,
                    **metrics,
                },
            )
            next_memory = now + max(5.0, args.memory_sample_sec)

        if now >= next_static_guard:
            violations = _static_guard_scan()
            static_guard_violations.extend(violations)
            _append_event(
                events_path,
                {
                    "ts": _now_iso(),
                    "event": "static_guard",
                    "violations_count": len(violations),
                },
            )
            next_static_guard = now + 3600.0

        time.sleep(max(0.1, args.interval_sec))

    quality = asyncio.run(_provider_quality_run())
    cache = _cache_history_correctness_check()

    memory_growth_pct = 0.0
    if memory_samples and memory_samples[0] > 0:
        memory_growth_pct = ((max(memory_samples) - memory_samples[0]) / memory_samples[0]) * 100.0

    soak = {
        "fail_calls": fail_calls,
        "translate_p50_ms": _percentile(translate_latencies, 0.50),
        "translate_p95_ms": _percentile(translate_latencies, 0.95),
        "translate_p99_ms": _percentile(translate_latencies, 0.99),
        "translate_max_ms": max(translate_latencies) if translate_latencies else 0.0,
        "n_restarts_max": max(restart_samples) if restart_samples else 0,
        "memory_growth_pct": memory_growth_pct,
        "cpu_p95_percent": _percentile(cpu_samples, 0.95),
        "cpu_max_percent": max(cpu_samples) if cpu_samples else 0.0,
    }

    reasons: list[str] = []
    if soak["n_restarts_max"] > 0:
        reasons.append("NRestarts > 0")
    if soak["fail_calls"] > 0:
        reasons.append("fail_calls > 0")
    if soak["memory_growth_pct"] > 20.0:
        reasons.append("memory growth > 20%")
    if soak["cpu_max_percent"] > STRICT_CPU_LIMIT_PERCENT:
        reasons.append("cpu max > strict limit")
    if quality["success_rate"] < 0.98:
        reasons.append("success_rate < 98%")
    if static_guard_violations:
        reasons.append("new non-network timeout/timer patterns detected")
    if quality["p50_ms"] > STRICT_LATENCY_LIMITS["p50_ms"]:
        reasons.append("p50 latency gate failed")
    if quality["p95_ms"] > STRICT_LATENCY_LIMITS["p95_ms"]:
        reasons.append("p95 latency gate failed")
    if quality["p99_ms"] > STRICT_LATENCY_LIMITS["p99_ms"]:
        reasons.append("p99 latency gate failed")
    if quality["max_ms"] > STRICT_LATENCY_LIMITS["max_ms"]:
        reasons.append("max latency gate failed")
    if quality["variants_violations"] > 0:
        reasons.append("variants_count > 8 detected")
    if not (
        cache["cache_ok"]
        and cache["history_ok"]
        and cache["ttl_absent_cache"]
        and cache["ttl_absent_history"]
        and cache["survives_short_wait"]
    ):
        reasons.append("cache/history correctness check failed")

    static_guard = {
        "violations_count": len(static_guard_violations),
        "violations": static_guard_violations,
    }
    gate = {
        "status": "passed" if not reasons else "failed",
        "reasons": reasons,
        "strict_latency_limits_ms": STRICT_LATENCY_LIMITS,
        "strict_cpu_limit_percent": STRICT_CPU_LIMIT_PERCENT,
    }

    summary = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "soak": soak,
        "quality": quality,
        "cache": cache,
        "static_guard": static_guard,
        "gate": gate,
    }

    _write_json(summary_path, summary)
    report_path.write_text(_build_report(summary), encoding="utf-8")

    return 0 if gate["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
