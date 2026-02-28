from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


def _preflight_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "tools" / "windows" / "vm" / "preflight_host.py"
    spec = importlib.util.spec_from_file_location("preflight_host", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load preflight_host module.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_meminfo_kib_extracts_numeric_values() -> None:
    module = _preflight_module()
    payload = "MemTotal:       16303824 kB\nMemAvailable:   8123456 kB\n"

    parsed = module.parse_meminfo_kib(payload)

    assert parsed["MemTotal"] == 16303824
    assert parsed["MemAvailable"] == 8123456


def test_select_ovmf_pair_prefers_secure_boot_code(tmp_path) -> None:
    module = _preflight_module()
    firmware_dir = tmp_path / "x64"
    firmware_dir.mkdir(parents=True)
    code_file = firmware_dir / "OVMF_CODE.secboot.4m.fd"
    vars_file = firmware_dir / "OVMF_VARS.4m.fd"
    code_file.write_text("code", encoding="utf-8")
    vars_file.write_text("vars", encoding="utf-8")

    selected_code, selected_vars = module.select_ovmf_pair([firmware_dir])

    assert selected_code == code_file
    assert selected_vars == vars_file


def test_parse_domcapabilities_detects_secure_and_tpm_emulator() -> None:
    module = _preflight_module()
    xml_payload = """
    <domainCapabilities>
      <os>
        <loader supported='yes'>
          <enum name='secure'>
            <value>yes</value>
            <value>no</value>
          </enum>
        </loader>
      </os>
      <devices>
        <tpm supported='yes'>
          <enum name='model'>
            <value>tpm-crb</value>
          </enum>
          <enum name='backendModel'>
            <value>emulator</value>
          </enum>
        </tpm>
      </devices>
    </domainCapabilities>
    """

    capabilities = module.parse_domcapabilities(xml_payload)

    assert capabilities.secure_loader_supported is True
    assert capabilities.tpm_supported is True
    assert "tpm-crb" in capabilities.tpm_models
    assert "emulator" in capabilities.tpm_backends
