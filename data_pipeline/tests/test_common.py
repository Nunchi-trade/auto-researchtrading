"""Tests for data_pipeline.common — all external deps mocked via sys.modules."""

import logging
import os
import sys
import types
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import common  # noqa: E402


def _make_df(start_ms: int, n_bars: int = 10) -> pd.DataFrame:
    return pd.DataFrame(
        {"timestamp": list(range(start_ms, start_ms + n_bars * 60000 * 15, 60000 * 15))}
    )


def _inject_mock_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


# ===================================================================
# find_best_result
# ===================================================================
class TestFindBestResult:
    def test_empty_list_returns_none(self):
        assert common.find_best_result([]) is None

    def test_all_negative_returns_returns_none(self):
        results = [
            {
                "total_return_pct": -5,
                "max_drawdown_pct": 2,
                "num_trades": 20,
                "_score": 1,
            },
            {
                "total_return_pct": -1,
                "max_drawdown_pct": 1,
                "num_trades": 30,
                "_score": 2,
            },
        ]
        assert common.find_best_result(results) is None

    def test_num_trades_less_than_10_returns_none(self):
        results = [
            {
                "total_return_pct": 10,
                "max_drawdown_pct": 2,
                "num_trades": 9,
                "_score": 5,
            },
        ]
        assert common.find_best_result(results) is None

    def test_zero_drawdown_returns_none(self):
        results = [
            {
                "total_return_pct": 10,
                "max_drawdown_pct": 0,
                "num_trades": 20,
                "_score": 5,
            },
        ]
        assert common.find_best_result(results) is None

    def test_negative_drawdown_returns_none(self):
        results = [
            {
                "total_return_pct": 10,
                "max_drawdown_pct": -1,
                "num_trades": 20,
                "_score": 5,
            },
        ]
        assert common.find_best_result(results) is None

    def test_returns_highest_score_among_valid(self):
        results = [
            {
                "total_return_pct": 5,
                "max_drawdown_pct": 1,
                "num_trades": 15,
                "_score": 3.0,
            },
            {
                "total_return_pct": 8,
                "max_drawdown_pct": 2,
                "num_trades": 20,
                "_score": 7.5,
            },
            {
                "total_return_pct": 3,
                "max_drawdown_pct": 0.5,
                "num_trades": 12,
                "_score": 2.0,
            },
        ]
        best = common.find_best_result(results)
        assert best is not None
        assert best["_score"] == 7.5

    def test_ignores_invalid_mixed_with_valid(self):
        results = [
            {
                "total_return_pct": -5,
                "max_drawdown_pct": 2,
                "num_trades": 20,
                "_score": 99,
            },
            {
                "total_return_pct": 10,
                "max_drawdown_pct": 0,
                "num_trades": 20,
                "_score": 50,
            },
            {
                "total_return_pct": 10,
                "max_drawdown_pct": 2,
                "num_trades": 5,
                "_score": 80,
            },
            {
                "total_return_pct": 6,
                "max_drawdown_pct": 1,
                "num_trades": 11,
                "_score": 4.0,
            },
        ]
        best = common.find_best_result(results)
        assert best is not None
        assert best["_score"] == 4.0

    def test_missing_keys_uses_defaults(self):
        results = [
            {"_score": 100, "max_drawdown_pct": 2, "num_trades": 20},
        ]
        assert common.find_best_result(results) is None


# ===================================================================
# compute_period
# ===================================================================
class TestComputePeriod:
    def test_empty_dict_returns_empty_string(self):
        assert common.compute_period({}) == ""

    def test_single_symbol_correct_format(self):
        start_ms = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        end_ms = int(datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
        df = pd.DataFrame({"timestamp": [start_ms, end_ms]})
        result = common.compute_period({"BTC": df})
        assert result == "2024-01-01_2024-01-02"

    def test_multiple_symbols_uses_min_start_max_end(self):
        s_a = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
        e_a = int(datetime(2024, 1, 5, tzinfo=timezone.utc).timestamp() * 1000)
        s_b = int(datetime(2024, 1, 2, tzinfo=timezone.utc).timestamp() * 1000)
        e_b = int(datetime(2024, 1, 8, tzinfo=timezone.utc).timestamp() * 1000)
        data = {
            "BTC": pd.DataFrame({"timestamp": [s_a, e_a]}),
            "ETH": pd.DataFrame({"timestamp": [s_b, e_b]}),
        }
        result = common.compute_period(data)
        assert result == "2024-01-01_2024-01-08"

    def test_timestamps_in_milliseconds(self):
        ts_ms = 1704067200000
        df = pd.DataFrame({"timestamp": [ts_ms]})
        result = common.compute_period({"SYM": df})
        assert result.startswith("2024-01-01")


# ===================================================================
# setup_logging
# ===================================================================
class TestSetupLogging:
    def test_returns_logger_with_correct_name(self):
        log = common.setup_logging("test_correct_name", "prefix")
        assert isinstance(log, logging.Logger)
        assert log.name == "test_correct_name"
        log.handlers.clear()

    def test_logger_has_debug_level(self):
        log = common.setup_logging("test_debug_level", "pfx")
        assert log.level == logging.DEBUG
        log.handlers.clear()

    def test_logger_has_two_handlers(self):
        name = f"test_two_handlers_{id(object())}"
        log = common.setup_logging(name, "pfx")
        assert len(log.handlers) == 2
        types_set = {type(h) for h in log.handlers}
        assert logging.StreamHandler in types_set
        assert logging.FileHandler in types_set
        log.handlers.clear()

    def test_idempotent_no_duplicate_handlers(self):
        name = f"test_idempotent_{id(object())}"
        log1 = common.setup_logging(name, "pfx")
        n1 = len(log1.handlers)
        log2 = common.setup_logging(name, "pfx")
        assert log2 is log1
        assert len(log2.handlers) == n1
        log1.handlers.clear()


# ===================================================================
# download_15m_data
# ===================================================================
class TestDownload15mData:
    @pytest.fixture(autouse=True)
    def _setup_mock_modules(self):
        mock_download = MagicMock()
        mock_load = MagicMock()
        mock_cache_dir = MagicMock(return_value="/tmp/cache")
        mock_symbols = ["BTC"]

        _inject_mock_module("backtest")
        _inject_mock_module(
            "backtest.backtest_interval",
            download_all_data=mock_download,
            load_data=mock_load,
            cache_data_dir=mock_cache_dir,
            SYMBOLS=mock_symbols,
        )
        self.mock_download = mock_download
        self.mock_load = mock_load
        self.mock_cache_dir = mock_cache_dir
        yield
        sys.modules.pop("backtest.backtest_interval", None)
        sys.modules.pop("backtest", None)

    def test_returns_data_when_download_succeeds_and_covers_range(self):
        needed_start_ms = int(time.time() * 1000) - (1300 * 3600 * 1000)
        df = _make_df(needed_start_ms - 7200000)
        data = {"BTC": df}
        self.mock_download.return_value = data

        result = common.download_15m_data()
        assert result == data
        self.mock_load.assert_not_called()

    def test_falls_back_to_cache_when_download_raises(self):
        self.mock_download.side_effect = Exception("network error")
        cached_data = {"BTC": _make_df(0)}
        self.mock_load.return_value = cached_data

        result = common.download_15m_data()
        assert result == cached_data

    def test_returns_empty_when_both_fail(self):
        self.mock_download.side_effect = Exception("network error")
        self.mock_load.side_effect = Exception("cache error")

        result = common.download_15m_data()
        assert result == {}

    def test_retries_after_clearing_cache_when_range_insufficient(self):
        needed_start_ms = int(time.time() * 1000) - (1300 * 3600 * 1000)
        bad_df = _make_df(needed_start_ms + 7200000 * 10)
        bad_data = {"BTC": bad_df}
        good_df = _make_df(needed_start_ms - 7200000)
        good_data = {"BTC": good_df}

        self.mock_download.side_effect = [bad_data, good_data]

        with patch("os.path.exists", return_value=False):
            result = common.download_15m_data()

        assert self.mock_download.call_count == 2
        assert result == good_data


# ===================================================================
# save_snapshots_to_db  (current: parsed: dict, period: str)
# ===================================================================
class TestSaveSnapshotsToDb:
    MOCK_DEFAULTS = {
        "SHORT_WINDOW": 24,
        "MED_WINDOW": 48,
        "EMA_FAST": 28,
        "EMA_SLOW": 104,
    }

    def _make_parsed(self):
        return {
            "per_symbol_params": {
                "BTC": {"SHORT_WINDOW": 30},
                "ETH": {"MED_WINDOW": 60},
            },
            "per_symbol_scores": {
                "BTC": 3.5,
                "ETH": 2.1,
            },
        }

    @pytest.fixture(autouse=True)
    def _setup_mock_modules(self):
        mock_pg = MagicMock()
        mock_tune = types.ModuleType("backtest.tune_15m")
        setattr(mock_tune, "DEFAULTS", self.MOCK_DEFAULTS)

        _inject_mock_module("backtest")
        sys.modules["backtest.tune_15m"] = mock_tune
        sys.modules["psycopg2"] = mock_pg

        self.mock_pg = mock_pg
        yield
        sys.modules.pop("backtest.tune_15m", None)
        sys.modules.pop("backtest", None)
        sys.modules.pop("psycopg2", None)

    def _mock_conn(self, fetchone_result=None):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = fetchone_result
        self.mock_pg.connect.return_value = mock_conn
        return mock_conn, mock_cur

    def test_returns_zero_when_db_url_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SUPABASE_DB_URL", None)
            result = common.save_snapshots_to_db(self._make_parsed())
        assert result == 0

    def test_inserts_correct_number_of_rows(self):
        mock_conn, mock_cur = self._mock_conn(fetchone_result=None)

        with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgres://fake"}):
            result = common.save_snapshots_to_db(
                self._make_parsed(), period="2024-01-01_2024-01-31"
            )

        assert result == 2
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_deactivates_previous_before_inserting(self):
        mock_conn, mock_cur = self._mock_conn(fetchone_result=(42,))

        with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgres://fake"}):
            common.save_snapshots_to_db(
                self._make_parsed(), period="2024-01-01_2024-01-31"
            )

        execute_calls = mock_cur.execute.call_args_list
        first_sql = execute_calls[0][0][0]
        assert "SELECT" in first_sql
        second_sql = execute_calls[1][0][0]
        assert "UPDATE" in second_sql
        assert "is_active = FALSE" in second_sql
        insert_calls = [c for c in execute_calls if "INSERT" in c[0][0]]
        assert len(insert_calls) == 2

    def test_rollback_and_return_zero_on_exception(self):
        mock_conn, mock_cur = self._mock_conn(fetchone_result=None)
        mock_cur.execute.side_effect = Exception("db error")

        with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgres://fake"}):
            result = common.save_snapshots_to_db(self._make_parsed())

        assert result == 0
        mock_conn.rollback.assert_called_once()

    def test_closes_connection_in_finally(self):
        mock_conn, mock_cur = self._mock_conn(fetchone_result=None)
        mock_cur.execute.side_effect = Exception("boom")

        with patch.dict(os.environ, {"SUPABASE_DB_URL": "postgres://fake"}):
            common.save_snapshots_to_db(self._make_parsed())

        mock_conn.close.assert_called_once()


# ===================================================================
# run_optimization_pipeline
# ===================================================================
class TestRunOptimizationPipeline:
    MOCK_DEFAULTS = {"SHORT_WINDOW": 24, "MED_WINDOW": 48, "EMA_FAST": 28}
    SINGLE_SWEEPS_MOCK = [("sw1", {"SHORT_WINDOW": [20, 24, 30]})]
    SECONDARY_SWEEPS_MOCK = [("sw2", {"EMA_FAST": [20, 28, 36]})]

    def _mock_data(self):
        return {"BTC": _make_df(1700000000000, n_bars=100)}

    def _mock_result(self, score=5.0, params=None):
        return {
            "_score": score,
            "params": params or {"SHORT_WINDOW": 30},
            "total_return_pct": 10,
            "max_drawdown_pct": 2,
            "num_trades": 50,
            "sharpe": 3,
            "profit_factor": 1.5,
            "win_rate_pct": 55,
            "sweep_name": "sw1",
        }

    def _make_tune_mock(self, **overrides):
        mock_tune = types.ModuleType("backtest.tune_15m")
        setattr(mock_tune, "DEFAULTS", self.MOCK_DEFAULTS)
        setattr(mock_tune, "SINGLE_SWEEPS", self.SINGLE_SWEEPS_MOCK)
        setattr(mock_tune, "SECONDARY_SWEEPS", self.SECONDARY_SWEEPS_MOCK)
        setattr(mock_tune, "build_adaptive_grid", MagicMock(return_value={}))
        setattr(mock_tune, "run_sweep", MagicMock(return_value=[]))
        setattr(
            mock_tune,
            "forward_stepwise_accumulate",
            MagicMock(return_value=({"SHORT_WINDOW": 30}, 4.0)),
        )
        setattr(
            mock_tune,
            "run_walk_forward",
            MagicMock(return_value={"avg_degradation": 0.2, "consistent": True}),
        )
        setattr(mock_tune, "subsample_data", MagicMock(side_effect=lambda d, n: d))
        setattr(mock_tune, "revalidate", MagicMock(return_value=[]))
        for k, v in overrides.items():
            setattr(mock_tune, k, v)
        return mock_tune

    @pytest.fixture(autouse=True)
    def _setup_and_teardown(self):
        _inject_mock_module("backtest")
        yield
        sys.modules.pop("backtest.tune_15m", None)
        sys.modules.pop("backtest", None)

    def test_returns_defaults_and_empty_when_no_results(self):
        mock_tune = self._make_tune_mock()
        sys.modules["backtest.tune_15m"] = mock_tune

        best, validated, wf = common.run_optimization_pipeline(
            self._mock_data(), skip_oos=True
        )
        assert best == self.MOCK_DEFAULTS.copy()
        assert isinstance(validated, list)
        assert wf is None

    def test_calls_run_sweep_for_single_and_secondary_sweeps(self):
        mock_run_sweep = MagicMock(return_value=[])
        mock_tune = self._make_tune_mock(run_sweep=mock_run_sweep)
        sys.modules["backtest.tune_15m"] = mock_tune

        common.run_optimization_pipeline(self._mock_data(), skip_oos=True)
        assert mock_run_sweep.call_count >= 2

    def test_uses_stepwise_params_when_stepwise_score_gte_best_single(self):
        best_single = self._mock_result(score=5.0, params={"SHORT_WINDOW": 30})

        def sweep_side_effect(*args, **kwargs):
            name = args[1] if len(args) > 1 else kwargs.get("name", "")
            if name == "ADAPTIVE_MULTI":
                return []
            return [best_single]

        mock_tune = self._make_tune_mock(
            run_sweep=MagicMock(side_effect=sweep_side_effect),
            revalidate=MagicMock(return_value=[best_single]),
            forward_stepwise_accumulate=MagicMock(
                return_value=({"SHORT_WINDOW": 50}, 7.0)
            ),
            build_adaptive_grid=MagicMock(return_value={"SHORT_WINDOW": [50]}),
        )
        sys.modules["backtest.tune_15m"] = mock_tune

        best, _, _ = common.run_optimization_pipeline(self._mock_data(), skip_oos=True)
        assert best.get("SHORT_WINDOW") == 50

    def test_uses_best_single_params_when_stepwise_score_lt_best_single(self):
        best_single = self._mock_result(score=8.0, params={"SHORT_WINDOW": 99})

        def sweep_side_effect(*args, **kwargs):
            name = args[1] if len(args) > 1 else kwargs.get("name", "")
            if name == "ADAPTIVE_MULTI":
                return []
            return [best_single]

        mock_tune = self._make_tune_mock(
            run_sweep=MagicMock(side_effect=sweep_side_effect),
            revalidate=MagicMock(return_value=[best_single]),
            forward_stepwise_accumulate=MagicMock(
                return_value=({"SHORT_WINDOW": 50}, 3.0)
            ),
            build_adaptive_grid=MagicMock(return_value={"SHORT_WINDOW": [99]}),
        )
        sys.modules["backtest.tune_15m"] = mock_tune

        best, _, _ = common.run_optimization_pipeline(self._mock_data(), skip_oos=True)
        assert best.get("SHORT_WINDOW") == 99

    def test_skips_walk_forward_when_skip_oos_true(self):
        mock_wf = MagicMock(return_value={"avg_degradation": 0.2, "consistent": True})
        mock_tune = self._make_tune_mock(run_walk_forward=mock_wf)
        sys.modules["backtest.tune_15m"] = mock_tune

        _, _, wf = common.run_optimization_pipeline(self._mock_data(), skip_oos=True)
        mock_wf.assert_not_called()
        assert wf is None

    def test_runs_walk_forward_when_skip_oos_false(self):
        mock_wf = MagicMock(return_value={"avg_degradation": 0.2, "consistent": True})
        mock_tune = self._make_tune_mock(run_walk_forward=mock_wf)
        sys.modules["backtest.tune_15m"] = mock_tune

        _, _, wf = common.run_optimization_pipeline(self._mock_data(), skip_oos=False)
        mock_wf.assert_called_once()
        assert wf is not None
        assert wf["avg_degradation"] == 0.2

    def test_attaches_ret_dd_to_all_validated_results(self):
        r1 = self._mock_result(score=5.0)
        r1["total_return_pct"] = 10.0
        r1["max_drawdown_pct"] = 2.0
        r2 = self._mock_result(score=3.0)
        r2["total_return_pct"] = 6.0
        r2["max_drawdown_pct"] = 3.0

        def sweep_side_effect(*args, **kwargs):
            name = args[1] if len(args) > 1 else kwargs.get("name", "")
            if name == "ADAPTIVE_MULTI":
                return []
            return [r1, r2]

        mock_tune = self._make_tune_mock(
            run_sweep=MagicMock(side_effect=sweep_side_effect),
            revalidate=MagicMock(return_value=[r1, r2]),
            forward_stepwise_accumulate=MagicMock(
                return_value=({"SHORT_WINDOW": 30}, 6.0)
            ),
        )
        sys.modules["backtest.tune_15m"] = mock_tune

        _, validated, _ = common.run_optimization_pipeline(
            self._mock_data(), skip_oos=True
        )

        for r in validated:
            assert "_ret_dd" in r
            expected = r["total_return_pct"] / max(r["max_drawdown_pct"], 0.01)
            assert abs(r["_ret_dd"] - expected) < 1e-9
