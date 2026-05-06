import pandas as pd
import numpy as np

from data.loader import _fetch_nse
from patterns.breakout import detect_breakout
from patterns.retest import detect_retest
from patterns.compression import detect_compression
from patterns.cup_handle import detect_cup_handle
from patterns.double_top_bottom import detect_double_top, detect_double_bottom
from patterns.darvas_box import detect_darvas_box
from patterns.flags import detect_flag_pennant, detect_pennant
from utils.pattern_validator import validate_pattern_quality
from utils.target_calculator import calculate_advanced_targets
from scoring.scorer import score_setup
from config.settings import MIN_CANDLES

# Pattern priority order — mirrors scanner.py
DETECTORS = [
    detect_cup_handle,
    detect_double_bottom,
    detect_double_top,
    detect_darvas_box,
    detect_flag_pennant,
    detect_pennant,
    detect_retest,
    detect_compression,
    detect_breakout,
]

MAX_HOLD_DAYS = 30


def _fetch_history(symbol, years):
    return _fetch_nse(symbol, days=years * 365)


def _detect_signal(df_slice):
    for detect in DETECTORS:
        try:
            result = detect(df_slice)
            if result:
                return result
        except Exception:
            continue
    return None


def _enrich_signal(df_slice, result):
    try:
        advanced = calculate_advanced_targets(df_slice, result["pattern"], result)
        result.update({
            "target1": advanced["targets"][0] if len(advanced["targets"]) > 0 else result["target"],
            "target2": advanced["targets"][1] if len(advanced["targets"]) > 1 else result["target"],
            "target3": advanced["targets"][2] if len(advanced["targets"]) > 2 else result["target"],
            "stop_loss": advanced["stop_loss"],
            "atr": advanced.get("atr", 0),
        })
    except Exception:
        result.setdefault("target1", result.get("target", 0))
        result.setdefault("target2", result.get("target", 0))
        result.setdefault("target3", result.get("target", 0))
        result.setdefault("atr", 0)

    try:
        is_valid, val_score, _ = validate_pattern_quality(df_slice, result["pattern"], result)
        if not is_valid:
            return None
        result["validation_score"] = val_score
    except Exception:
        result["validation_score"] = 0

    try:
        score, rr, upside, risk = score_setup(result)
        if rr == 0 or risk <= 0:
            return None
        result["score"] = round(score, 2)
        result["rr"] = round(rr, 2)
    except Exception:
        result["score"] = 0
        result["rr"] = 0

    return result


def _close_trade(trade, exit_price, exit_date, exit_reason):
    trade["exit_price"] = exit_price
    trade["exit_date"] = exit_date
    trade["exit_reason"] = exit_reason
    trade["pnl_pct"] = round(
        (exit_price - trade["entry_price"]) / trade["entry_price"] * 100, 2
    )
    trade["result"] = "WIN" if trade["pnl_pct"] > 0 else "LOSS"
    return trade


def backtest_symbol(symbol, years=2, min_score=30, scan_every=5):
    """
    Walk-forward backtest for a single symbol.

    Entry rule: next bar's open after signal detection (no lookahead).
    Exit rules (checked in priority order each bar):
      1. Low <= stop_loss  → exit at stop_loss
      2. High >= target3   → exit at target3
      3. High >= target2   → exit at target2
      4. High >= target1   → exit at target1
      5. days_held >= MAX_HOLD_DAYS → exit at close
    """
    df = _fetch_history(symbol, years)
    if df is None or len(df) < MIN_CANDLES + 10:
        return []

    trades = []
    open_trade = None
    last_scan_idx = 0

    for i in range(MIN_CANDLES, len(df)):
        current_date = df.index[i]
        row = df.iloc[i]
        low = float(row["Low"])
        high = float(row["High"])
        close = float(row["Close"])

        # --- Manage open trade first ---
        if open_trade is not None:
            entry_price = open_trade["entry_price"]
            days_held = (current_date - open_trade["entry_date"]).days

            if low <= open_trade["stop_loss"]:
                trades.append(_close_trade(open_trade, open_trade["stop_loss"], current_date, "Stop Loss"))
                open_trade = None
                continue

            if high >= open_trade["target3"]:
                trades.append(_close_trade(open_trade, open_trade["target3"], current_date, "Target 3"))
                open_trade = None
                continue

            if high >= open_trade["target2"]:
                trades.append(_close_trade(open_trade, open_trade["target2"], current_date, "Target 2"))
                open_trade = None
                continue

            if high >= open_trade["target1"]:
                trades.append(_close_trade(open_trade, open_trade["target1"], current_date, "Target 1"))
                open_trade = None
                continue

            if days_held >= MAX_HOLD_DAYS:
                trades.append(_close_trade(open_trade, close, current_date, "Time Exit"))
                open_trade = None
                continue

        # --- Scan for new signal ---
        if open_trade is None and (i - last_scan_idx) >= scan_every:
            last_scan_idx = i
            df_slice = df.iloc[: i + 1].copy()

            result = _detect_signal(df_slice)
            if result:
                result = _enrich_signal(df_slice, result)
                if result and result.get("score", 0) >= min_score:
                    # Enter at next bar's open to avoid lookahead
                    if i + 1 >= len(df):
                        continue
                    entry_price = float(df.iloc[i + 1]["Open"])
                    stop_loss = result["stop_loss"]

                    # Skip if stop is already above entry (gapped down)
                    if stop_loss >= entry_price:
                        continue

                    open_trade = {
                        "symbol": symbol,
                        "pattern": result["pattern"],
                        "signal_date": current_date,
                        "entry_date": df.index[i + 1],
                        "entry_price": entry_price,
                        "stop_loss": stop_loss,
                        "target1": result["target1"],
                        "target2": result["target2"],
                        "target3": result["target3"],
                        "score": result["score"],
                        "rr": result["rr"],
                        "status": result.get("status", ""),
                        "exit_price": None,
                        "exit_date": None,
                        "exit_reason": None,
                        "pnl_pct": None,
                        "result": None,
                    }

    # Close any remaining open trade at last bar
    if open_trade is not None:
        last_close = float(df.iloc[-1]["Close"])
        last_date = df.index[-1]
        trades.append(_close_trade(open_trade, last_close, last_date, "End of Data"))

    return trades


def backtest_portfolio(symbols, years=2, min_score=30, scan_every=5):
    """Run backtest across a list of symbols and return all trades."""
    all_trades = []
    for sym in symbols:
        print(f"  Backtesting {sym}...", end=" ", flush=True)
        trades = backtest_symbol(sym, years=years, min_score=min_score, scan_every=scan_every)
        print(f"{len(trades)} trades")
        all_trades.extend(trades)
    return all_trades
