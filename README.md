# Enhanced Swing Trading Screener — NSE India

A swing trading screener for Indian stocks (NSE) with Cup & Handle detection, momentum scoring, dynamic universe building, and walk-forward backtesting.

---

## Iteration History

### v1.0 → v4.0 — Original Build (pre May 2026)
**The original concept:**

The screener started as a pattern detection tool for Indian swing trading. The idea was simple — scan a watchlist of stocks, find chart patterns (Cup & Handle, Double Bottom, Darvas Box, Flags), and output ranked setups with entry, stop, and target.

**What it had:**
- `yfinance` as data source (Yahoo Finance)
- 10+ pattern detectors: Cup & Handle, Double Top/Bottom, Darvas Box, Flags/Pennants, Breakout, Retest, Compression
- `utils/sector_analyzer.py` — sector trend analysis
- `utils/performance_tracker.py` — historical win/loss tracking per pattern
- `utils/verification_tools.py` — 4-category manual checklist (16 verification points)
- `utils/entry_confirmation.py` — multi-indicator entry signal (price action + volume + momentum + timeframe)
- `utils/target_calculator.py` — multi-level targets (conservative / moderate / aggressive)
- `scoring/scorer.py` — setup quality scoring 0-100
- `main.py` — entry point, scan ~30 stocks from `stocks.txt`
- Data fetched sequentially, one stock at a time

**Problems we hit:**
- yfinance data for Indian stocks was inconsistent and sometimes stale
- Sequential fetching made full scans take 15-20 minutes
- Cup & Handle logic had no U-shape validation — was detecting V-shapes and edge cases as cups
- No backtester to validate which patterns actually worked
- Stock universe was a small manual list (~30 stocks), no momentum filtering
- Double Bottom had a 19.5% win rate in backtests — was the biggest drag on results

---

### v5.0 — 2026-05-07 (Current)
**What we rebuilt and why:**

**1. Switched data source: yfinance → jugaad-data (NSE native)**
- jugaad-data pulls directly from NSE — accurate OHLCV, correct Indian market calendar
- Fixed Windows `os.makedirs` bug in jugaad-data (monkey-patched at import)
- Auto-strips `.NS` / `.BO` suffix before API call

**2. Parallel fetching + disk cache (`data/fetcher.py`)**
- Old: sequential, 15-20 min for 200 stocks
- New: 10-15 ThreadPoolExecutor workers, <30 sec on cached runs
- 8-hour TTL cache in `cache/` folder — run it in the morning, same data all day

**3. Rewrote Cup & Handle (`patterns/cup_handle.py`)**
- Added U-shape validator: cup bottom must be in middle 60% of the bar range (not at edges)
- Two variants: daily (60-bar cup, 15-bar handle) and weekly (65-bar cup, 12-bar handle)
- Weekly C&H is highest priority — catches longer institutional setups like you see on TradingView
- Breakout level = left rim resistance (not 52w high — that was causing ₹748 stocks showing ₹1,434 breakout)
- Near threshold loosened to 15% for weekly — weekly patterns need more room

**4. New focused screener (`may_screener.py`)**
- Dropped Double Bottom entirely (19.5% win rate in backtest)
- Pattern priority: Weekly C&H > Daily C&H > Darvas Box > Flag/Pennant > Breakout > No Pattern
- "No Pattern" stocks get breakout = 20-day high (realistic near-term resistance)
- Skips any stock where breakout > 20% above CMP (not reachable in swing timeframe)
- Skips trades with RR < 1.0
- Scoring: Pattern (40) + RSI zone (20) + RS vs Nifty (15) + 52w proximity (15) + Volume (10) + MA alignment (10) + RR bonus (10)

**5. Dynamic universe builder (`stock_universe.py`)**
- Scores all 233 nifty500 stocks daily: near 52w high + above MA50/MA20 + volume surge
- Top 80 momentum stocks + backbone50 (always included) = today's scan list
- Saves to `today_universe.txt`

**6. Curated stock lists**
- `backbone50.txt` — 48 stocks: precision engineering, data center, power infra, networking
- `nifty500.txt` — 233 stocks across all sectors as full universe

**7. Walk-forward backtester (`backtester/`)**
- Slices data day-by-day, no lookahead bias
- Entry at next bar open, exits on stop / target / 20-day time stop
- P&L breakdown by pattern type and exit reason

**8. One-click runner (`run_screener.bat`)**
- Runs universe builder then screener in sequence
- Manual only — no Windows Task Scheduler

---

## How to Run

Double-click `run_screener.bat`

```
[1/2] stock_universe.py  → scores 233 stocks, picks top 80 + backbone50 → today_universe.txt
[2/2] may_screener.py    → scans today_universe.txt for setups → daily_results.csv
```

- First run: ~2-3 min (fetching fresh NSE data)
- Same day reruns: ~30 sec (cached)
- Best time: run before market open (9:00-9:15 AM IST)

---

## Installation

```bash
git clone https://github.com/karthik0419/enhanced-swing-trading-screener
cd enhanced-swing-trading-screener
pip install pandas numpy jugaad-data
```

---

## Project Structure

```
enhanced-swing-trading-screener/
├── run_screener.bat          # One-click manual runner
├── may_screener.py           # Main swing screener
├── stock_universe.py         # Dynamic universe builder
├── backtest.py               # Backtester CLI
├── backbone50.txt            # 48 curated stocks (always scanned)
├── nifty500.txt              # 233-stock full universe
│
├── data/
│   ├── loader.py             # NSE fetcher via jugaad-data
│   └── fetcher.py            # Parallel fetch + 8-hour disk cache
│
├── patterns/
│   ├── cup_handle.py         # Cup & Handle — daily + weekly
│   ├── breakout.py           # Resistance breakout
│   ├── darvas_box.py         # Darvas Box
│   └── flags.py              # Flag / Pennant
│
├── backtester/
│   ├── engine.py             # Walk-forward engine
│   └── report.py             # P&L stats by pattern
│
├── engine/
│   └── scanner.py            # Core scan loop
│
└── cache/                    # Auto-generated, gitignored
```

---

## Scoring System

| Factor | Max | Logic |
|--------|-----|-------|
| Pattern quality | 40 | Weekly C&H=40, Daily C&H=35, Darvas=28, Flag=25, Breakout=20 |
| RSI zone | 20 | 45-65 healthy = 20pts, 35-45 recovering = 12pts, >65 overbought = 8pts |
| Relative strength vs Nifty | 15 | RS +5% = 15pts, RS +2% = 10pts, RS +0% = 5pts |
| Near 52-week high | 15 | Within 5% = 15pts, within 10% = 10pts, within 15% = 5pts |
| Volume surge | 10 | 1.5x avg = 10pts, 1.2x avg = 5pts |
| MA alignment | 10 | Price > MA20 > MA50 = 10pts, price > MA20 = 5pts |
| RR bonus | 10 | RR >= 2.5 = 10pts, RR >= 1.5 = 5pts |

Min score for results: 30 (change with `--min-score`)

---

## Cup & Handle Parameters

| | Daily | Weekly |
|--|-------|--------|
| Cup length | 40-80 bars | 50-80 bars |
| Cup depth | 10-40% | 15-50% |
| Handle length | 10-20 bars | 8-15 bars |
| Handle retrace | max 40% of cup | max 40% of cup |
| Near breakout | within 8% | within 15% |
| U-shape check | bottom in middle 60% | bottom in middle 60% |

---

## Output Columns

| Column | Description |
|--------|-------------|
| symbol | NSE stock symbol |
| pattern | Detected pattern |
| cmp | Current market price |
| breakout | Resistance level to watch |
| stop_loss | ATR-based stop |
| target | Price target |
| upside_% | Upside to target |
| risk_% | Downside to stop |
| rr | Risk/Reward ratio |
| rsi | 14-period RSI |
| vol_ratio | Today's volume vs 20-day avg |
| dist_52h_% | % below 52-week high |
| score | Setup score (0-100) |
| reasons | What drove the score |

---

## Backtesting

```bash
python backtest.py --stocks backbone50.txt --start 2024-01-01
```

---

## Known Limitations

- `rs_vs_nifty` = 0.0 for all — jugaad-data does not support index symbols (`^NSEI`), so Nifty benchmark comparison is not available
- Some stocks fail to fetch (PRICOL, NIIT, MASTEK etc.) — NSE API returns a different column schema for certain scrips; screener skips them silently
- End-of-day data only — not suitable for intraday

---

## Disclaimer

For educational purposes only. Trading involves substantial risk of loss. Never trade with money you cannot afford to lose.
