import importlib
import os
import subprocess
import sys

from centerfield_visitor_mcp import config as config_module
from centerfield_visitor_mcp.config import Settings, _mask_mobile, settings


def test_missing_required_lists_env_names(unconfigured):
    assert unconfigured.missing_required() == ["CF_COMPANY_NAME", "CF_PERSON_IN_CHARGE_MOBILE"]


def test_missing_required_empty_when_configured(configured):
    assert configured.missing_required() == []


def test_startup_problems_default_floor(monkeypatch):
    monkeypatch.setattr(settings, "default_floor", "13")
    assert any("CF_DEFAULT_FLOOR" in p for p in settings.startup_problems())
    monkeypatch.setattr(settings, "default_floor", "18")
    assert settings.startup_problems() == []


def test_file_tools_follow_transport(monkeypatch):
    monkeypatch.setattr(settings, "expose_file_tools", None)
    monkeypatch.setattr(settings, "transport", "stdio")
    assert settings.file_tools_enabled is True
    monkeypatch.setattr(settings, "transport", "streamable-http")
    assert settings.file_tools_enabled is False
    monkeypatch.setattr(settings, "expose_file_tools", True)
    assert settings.file_tools_enabled is True


def test_allowed_hosts_parsing(monkeypatch):
    monkeypatch.setattr(settings, "http_allowed_hosts", " mcp.example.com, localhost:8000 ,")
    assert settings.allowed_hosts == ["mcp.example.com", "localhost:8000"]


def test_public_summary_masks_mobile(configured):
    summary = configured.public_summary()
    assert "01000000000" not in summary["person_in_charge_mobile"]
    assert summary["person_in_charge_mobile"].startswith("010") and summary["person_in_charge_mobile"].endswith("00")
    assert summary["company_name"] == "Test Tenant Inc."


def test_mask_mobile_edge_cases():
    assert _mask_mobile("") == "(unset)"
    assert _mask_mobile("123") == "***"
    assert _mask_mobile("01012345678") == "010******78"


def test_env_precedence_process_env_over_env_file(tmp_path):
    """CF_ENV_FILE is read at import time, so exercise it in a subprocess."""
    env_file = tmp_path / "cf.env"
    env_file.write_text("CF_COMPANY_NAME=FromFile\nCF_PERSON_IN_CHARGE_MOBILE=01011112222\nCF_DEFAULT_FLOOR=18\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("CF_")}
    env.update({"CF_ENV_FILE": str(env_file), "CF_COMPANY_NAME": "FromProcess", "HOME": str(tmp_path)})
    code = (
        "from centerfield_visitor_mcp.config import settings;"
        "print(settings.company_name, settings.person_in_charge_mobile, settings.default_floor, len(settings.loaded_env_files()))"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=str(tmp_path), capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["FromProcess", "01011112222", "18", "1"]


def test_env_file_candidates_include_cf_env_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CF_ENV_FILE", str(tmp_path / "nope.env"))
    files = config_module._env_files()
    assert str(files[-1]).endswith("nope.env")
    assert len(files) == len({p.resolve() for p in files})  # de-duplicated


def test_loaded_env_files_only_lists_existing_files():
    s = Settings(company_name="x", person_in_charge_mobile="01000000000")
    assert all(os.path.isfile(f) for f in s.loaded_env_files())
