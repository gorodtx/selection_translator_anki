from __future__ import annotations

from desktop_app.platform import (
    LinuxGnomeAdapter,
    MacOSAdapter,
    OtherPlatformAdapter,
    PlatformTarget,
    WindowsAdapter,
)
from desktop_app.platform import factory


def test_linux_gnome_resolves_linux_adapter(monkeypatch) -> None:
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")

    adapter = factory.resolve_platform_adapter()

    assert isinstance(adapter, LinuxGnomeAdapter)
    assert adapter.target is PlatformTarget.LINUX_GNOME
    assert adapter.capabilities.production_supported is True


def test_linux_non_gnome_resolves_other_adapter(monkeypatch) -> None:
    monkeypatch.setattr(factory.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")

    adapter = factory.resolve_platform_adapter()

    assert isinstance(adapter, OtherPlatformAdapter)
    assert adapter.target is PlatformTarget.OTHER
    assert adapter.capabilities.production_supported is False


def test_windows_resolves_windows_adapter(monkeypatch) -> None:
    monkeypatch.setattr(factory.sys, "platform", "win32")

    adapter = factory.resolve_platform_adapter()

    assert isinstance(adapter, WindowsAdapter)
    assert adapter.target is PlatformTarget.WINDOWS
    assert adapter.capabilities.production_supported is False


def test_macos_resolves_macos_adapter(monkeypatch) -> None:
    monkeypatch.setattr(factory.sys, "platform", "darwin")

    adapter = factory.resolve_platform_adapter()

    assert isinstance(adapter, MacOSAdapter)
    assert adapter.target is PlatformTarget.MACOS
    assert adapter.capabilities.production_supported is False
