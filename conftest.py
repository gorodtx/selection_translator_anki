from __future__ import annotations

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # In this repository, dev-only tests live in `dev/` and are not shipped.
    # Pytest uses exit code 5 when no tests are collected, which would fail our
    # quality gate. Treat "no tests" as success.
    if exitstatus == 5:
        session.exitstatus = 0
