"""Unit tests for one-time activation licensing."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import license as license_util


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HM_LICENSE_KEY", raising=False)


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(license_util, "license_path", lambda: tmp_path / "license.json")
    return tmp_path


class TestKeyValidation:
    def test_generated_key_validates(self) -> None:
        key = license_util.generate_key()
        assert license_util.validate_key(key) is True

    def test_key_format(self) -> None:
        key = license_util.generate_key()
        assert key.startswith("HM-")
        assert len(key) == 3 + 8 * 5 - 1  # prefix + 8 groups of 4 hex + 7 dashes

    def test_lowercase_and_no_dashes_validate(self) -> None:
        key = license_util.generate_key()
        assert license_util.validate_key(key.lower()) is True
        assert license_util.validate_key(key.replace("-", "")) is True
        assert license_util.validate_key(key[3:]) is True

    def test_tampered_key_invalid(self) -> None:
        key = license_util.generate_key()
        tampered = key[:-2] + ("00" if not key.endswith("00") else "11")
        assert license_util.validate_key(tampered) is False

    def test_garbage_invalid(self) -> None:
        for bad in ("", "  ", "not-a-key", "HM-0000-0000-0000-0000", "ABCDEF" * 6):
            assert license_util.validate_key(bad) is False

    def test_signature_mismatch_invalid(self) -> None:
        key = license_util.generate_key()
        raw = license_util._normalize(key)
        flipped = raw[:8] + ("1" if raw[8] != "1" else "2") + raw[9:]
        assert license_util.validate_key(flipped) is False


class TestActivation:
    def test_activate_then_activated(self, store: Path) -> None:
        key = license_util.generate_key()
        ok, err = license_util.activate(key)
        assert ok is True
        assert err == ""
        assert license_util.is_activated() is True
        assert (store / "license.json").exists()

    def test_activation_persists_across_reload(self, store: Path) -> None:
        key = license_util.generate_key()
        license_util.activate(key)
        record = license_util._read_license()
        assert license_util.validate_key(record["key"]) is True
        assert "activated_at" in record

    def test_status_reports_activated(self, store: Path) -> None:
        key = license_util.generate_key()
        license_util.activate(key)
        status = license_util.status()
        assert status["activated"] is True
        assert status["key_hint"].startswith("HM-")
        assert status["price"] == 20.0
        assert status["currency"] == "USD"

    def test_not_activated_by_default(self, store: Path) -> None:
        assert license_util.is_activated() is False
        status = license_util.status()
        assert status["activated"] is False
        assert status["key_hint"] == ""

    def test_invalid_key_rejected(self, store: Path) -> None:
        ok, err = license_util.activate("NOT-A-REAL-KEY")
        assert ok is False
        assert err
        assert license_util.is_activated() is False

    def test_empty_key_rejected(self, store: Path) -> None:
        assert license_util.activate("") == (False, "Please paste your license key.")
        assert license_util.activate("   ") == (False, "Please paste your license key.")

    def test_env_var_activates_without_file(self, store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = license_util.generate_key()
        monkeypatch.setenv("HM_LICENSE_KEY", key)
        assert license_util.is_activated() is True
        assert not (store / "license.json").exists()

    def test_invalid_env_var_not_activated(self, store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HM_LICENSE_KEY", "garbage")
        assert license_util.is_activated() is False
