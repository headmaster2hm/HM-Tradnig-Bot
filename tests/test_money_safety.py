"""Money-safety unit tests for risk gates, DB stats, and live order hard-fail."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.config_loader import AppConfig
from database.db import TradeDatabase
from execution.mt5_client import MT5Client
from execution.risk_manager import RiskManager
from execution.trade_executor import TradeExecutor


def _config(**overrides) -> AppConfig:
    cfg = AppConfig(
        dry_run=True,
        daily_profit_target=50.0,
        daily_loss_limit=30.0,
        spread_limit=150.0,
        cooldown_candles=0,
        max_trades_per_day=10,
        stop_loss_points=200.0,
        take_profit_points=300.0,
        lot_size=0.2,
        session_start="00:00",
        session_end="23:59",
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


class TestRiskManager:
    def test_daily_profit_target_halts(self) -> None:
        risk = RiskManager(_config())
        just = risk.register_close(50.0)
        assert just is True
        assert risk.halted is True
        assert "profit" in risk.halt_reason.lower()
        decision = risk.can_trade(spread=10)
        assert decision.allowed is False

    def test_daily_loss_limit_halts(self) -> None:
        risk = RiskManager(_config())
        just = risk.register_close(-30.0)
        assert just is True
        assert risk.halted is True
        assert "loss" in risk.halt_reason.lower()
        assert risk.can_trade(10).allowed is False

    def test_loss_accumulates_before_halt(self) -> None:
        risk = RiskManager(_config())
        assert risk.register_close(-10.0) is False
        assert risk.halted is False
        assert risk.register_close(-20.0) is True
        assert risk.day_profit == -30.0
        assert risk.halted is True

    def test_spread_blocks_entry(self) -> None:
        risk = RiskManager(_config(spread_limit=20))
        decision = risk.can_trade(spread=50)
        assert decision.allowed is False
        assert "Spread" in decision.reason

    def test_max_trades_per_day(self) -> None:
        risk = RiskManager(_config(max_trades_per_day=2, cooldown_candles=0))
        risk.register_open()
        risk.register_open()
        decision = risk.can_trade(spread=5)
        assert decision.allowed is False
        assert "Max trades" in decision.reason

    def test_cooldown_blocks_until_candles_pass(self) -> None:
        risk = RiskManager(_config(cooldown_candles=3))
        risk.register_close(1.0)
        assert risk.can_trade(5).allowed is False
        risk.on_new_candle()
        risk.on_new_candle()
        risk.on_new_candle()
        assert risk.can_trade(5).allowed is True

    def test_fixed_lot_when_risk_sizing_off(self) -> None:
        risk = RiskManager(_config(lot_size=0.2, use_risk_sizing=False))
        assert risk.position_size(10_000, stop_points=200) == 0.2


class TestTradeDatabaseStats:
    def test_stats_separate_paper_and_live(self, tmp_path: Path) -> None:
        db = TradeDatabase(tmp_path / "trades.db")
        db.insert_open(1, "BUY", 1.1, 0.2, "paper", dry_run=True)
        db.close_trade(1, 1.2, 10.0, "test")
        db.insert_open(2, "SELL", 1.1, 0.2, "live", dry_run=False)
        db.close_trade(2, 1.0, -4.0, "test")

        paper = db.stats(dry_run=True)
        live = db.stats(dry_run=False)
        all_stats = db.stats(dry_run=None)

        assert paper["total_trades"] == 1
        assert paper["net_profit"] == 10.0
        assert paper["win_rate"] == 100.0

        assert live["total_trades"] == 1
        assert live["net_profit"] == -4.0
        assert live["win_rate"] == 0.0

        assert all_stats["total_trades"] == 2
        assert all_stats["net_profit"] == 6.0

    def test_open_tickets_filter(self, tmp_path: Path) -> None:
        db = TradeDatabase(tmp_path / "trades.db")
        db.insert_open(11, "BUY", 1.1, 0.2, "paper", dry_run=True)
        db.insert_open(22, "BUY", 1.1, 0.2, "live", dry_run=False)
        assert db.open_tickets(dry_run=True) == [11]
        assert db.open_tickets(dry_run=False) == [22]


class TestLiveNoPaperFallback:
    def test_live_open_fails_when_disconnected(self) -> None:
        client = MT5Client(_config(dry_run=False, stop_loss_points=200, symbol="EURUSD"))
        client.connected = False
        client._mt5 = None
        client.ensure_connected = lambda: False  # type: ignore[method-assign]
        result = client.open_market("BUY", 0.2, sl=1.0, tp=2.0)
        assert result is None
        assert "live orders blocked" in client.last_error.lower()
        assert client._paper_positions == []

    def test_dry_run_still_opens_paper(self) -> None:
        client = MT5Client(_config(dry_run=True))
        result = client.open_market("BUY", 0.2, sl=1.0, tp=2.0)
        assert result is not None
        assert result["type"] == "BUY"
        assert len(client._paper_positions) == 1


class TestStopLossPrices:
    def test_sl_tp_use_symbol_point(self) -> None:
        cfg = _config(dry_run=True, stop_loss_points=200, take_profit_points=300)
        executor = TradeExecutor(cfg)
        executor.client.symbol_point = lambda: 0.00001  # type: ignore[method-assign]
        executor.client.symbol_status = lambda side=None: {"stops_level": 0}  # type: ignore[method-assign]

        sl, tp = executor._sl_tp_prices("BUY", entry=1.10000)
        assert abs(sl - (1.10000 - 200 * 0.00001)) < 1e-9
        assert abs(tp - (1.10000 + 300 * 0.00001)) < 1e-9

        sl, tp = executor._sl_tp_prices("SELL", entry=1.10000)
        assert abs(sl - (1.10000 + 200 * 0.00001)) < 1e-9
        assert abs(tp - (1.10000 - 300 * 0.00001)) < 1e-9

    def test_live_start_blocked_without_stop_loss(self) -> None:
        cfg = _config(dry_run=False, stop_loss_points=0)
        client = MT5Client(cfg)
        blockers = client.live_readiness()
        assert any("Stop loss" in b for b in blockers)


class TestConfigDefaults:
    def test_defaults_prefer_dry_run_and_sl(self) -> None:
        cfg = AppConfig()
        assert cfg.dry_run is True
        assert cfg.stop_loss_points > 0


class TestSecretsAndHardening:
    def test_sanitize_strips_password_by_default(self) -> None:
        from config.secrets import sanitize_config_for_disk

        cfg = _config()
        cfg.mt5.password = "secret"
        cfg.mt5.remember_password = False
        cfg.telegram.bot_token = "token"
        cfg.telegram.remember_token = False
        clean = sanitize_config_for_disk(cfg)
        assert clean.mt5.password == ""
        assert clean.telegram.bot_token == ""
        assert cfg.mt5.password == "secret"  # original untouched

    def test_sanitize_keeps_password_when_remembered(self) -> None:
        from config.secrets import sanitize_config_for_disk

        cfg = _config()
        cfg.mt5.password = "secret"
        cfg.mt5.remember_password = True
        clean = sanitize_config_for_disk(cfg)
        assert clean.mt5.password == "secret"

    def test_harden_forces_dry_run_without_sl(self) -> None:
        from config.secrets import harden_runtime_config

        cfg = _config(dry_run=False, stop_loss_points=0)
        notices = harden_runtime_config(cfg)
        assert cfg.dry_run is True
        assert notices

    def test_env_password_overrides_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from config.secrets import ENV_MT5_PASSWORD, resolve_mt5_password

        cfg = _config()
        cfg.mt5.password = "file-pass"
        monkeypatch.setenv(ENV_MT5_PASSWORD, "env-pass")
        assert resolve_mt5_password(cfg) == "env-pass"

    def test_reset_daily_limits(self) -> None:
        risk = RiskManager(_config())
        risk.register_close(-30.0)
        assert risk.halted is True
        risk.reset_daily_limits()
        assert risk.halted is False
        assert risk.day_profit == 0.0
        assert risk.can_trade(5).allowed is True
