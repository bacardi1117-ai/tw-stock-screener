# choose_stock

Python 3.12 project for Taiwan stock market data. Phase 2 stores TWSE/TPEx lists and daily quotes. Phase 3 adds FinMind monthly revenue and quarterly fundamentals for a small, explicitly selected set of stocks.

## FinMind token and commands

Create a FinMind free account and set `FINMIND_TOKEN` as a Windows user environment variable through the Environment Variables dialog, then open a new terminal. Do not put the token in this repository, a command line, or a log. The program reads the environment variable and prints `[ERROR] FINMIND_TOKEN is not set` when it is absent.

Run a small set of stocks:

```powershell
python src/main.py fundamentals --stocks 2330,2317,2454
python src/main.py fundamentals --limit 10
```

The stock names come from `data/market/stocks.csv`. Each run reads only these selected stocks, not the whole market.

## Output and calculations

`data/revenue/YYYY.csv` contains `date`, `year`, `month`, `stock_id`, `stock_name`, `revenue`, `revenue_mom`, and `revenue_yoy`. FinMind's `revenue_year` and `revenue_month` identify the revenue period; its `date` is retained separately. MoM and YoY are calculated from the preceding month and the same month a year earlier. Both are stored as percentage numbers: `12.5` means +12.5%. Missing or nonpositive comparison bases produce an empty field.

`data/financials/YYYY.csv` contains the report date, year, quarter, stock identity, EPS, quarterly revenue and profit, assets, liabilities, equity, operating cash flow, capital expenditure, and the derived metrics. It also retains the cash-flow year-to-date values needed to calculate standalone quarters on later incremental runs.

### 財報期間口徑

FinMind `TaiwanStockFinancialStatements` returns **single-quarter** `EPS`, `Revenue`, `GrossProfit`, `OperatingIncome`, and `IncomeAfterTaxes` for Q1–Q4. The CSV names these `eps_single`, `revenue_single`, `gross_profit_single`, `operating_income_single`, and `net_income_single`. They must not be differenced between quarters. FinMind explicitly documents `EPS` as single-quarter and warns that adding quarterly EPS may not reproduce a published cumulative EPS after share-count adjustments. Accordingly, the CSV does **not** invent `eps_cumulative` or cumulative income-statement columns. Source: [FinMind fundamentals documentation](https://finmind.github.io/tutor/TaiwanMarket/Fundamental/).

The values were cross-checked against [TSMC's 2026 Q2 consolidated report](https://investor.tsmc.com/sites/ir/financial-report/2026/TSMC%202026Q2%20Consolidated%20Financial%20Statements_E_0.pdf): 2026 Q2 single-quarter basic EPS is NT$27.25, while its separately reported H1 cumulative basic EPS is NT$49.33. The latter is a published comparison value, not a FinMind `eps_cumulative` field. The report separately presents three-month income statements and six-month cash flows.

`TaiwanStockCashFlowsStatement` supplies year-to-date cash flows for Q1–Q4. The CSV has both `operating_cash_flow_cumulative` and `operating_cash_flow_single`, and positive-spending `capital_expenditure_cumulative` and `capital_expenditure_single`. Q1 single equals Q1 cumulative; each later single quarter equals the current cumulative amount less the previous quarter's cumulative amount in the same year. `free_cash_flow_cumulative` and `free_cash_flow_single` each subtract the corresponding positive capital expenditure from operating cash flow. The raw negative capex source value is retained in `capital_expenditure_ytd` for incremental recalculation.

`TaiwanStockBalanceSheet` contains **quarter-end balances** (`total_assets`, `total_liabilities`, `equity`); they are never differenced. `roe_quarterly_approx` divides single-quarter net income by average beginning and ending equity, falling back to ending equity if the prior balance is unavailable. It is not annualized. For compatibility, `eps`, `revenue`, `gross_profit`, `operating_income`, `net_income`, `gross_margin`, `operating_margin`, `operating_cash_flow`, `capital_expenditure`, `free_cash_flow`, and `roe` remain aliases for their `*_single` or `roe_quarterly_approx` counterparts. The explicit columns should be used for new code.

- `gross_margin_single = gross_profit_single / revenue_single × 100` and `operating_margin_single = operating_income_single / revenue_single × 100`.
- `gross_margin_qoq`, `gross_margin_yoy`, `operating_margin_qoq`, and `operating_margin_yoy` are **percentage-point differences**.
- `eps_qoq` and `eps_yoy` compare **single-quarter EPS**. A zero, missing, or negative comparison EPS produces an empty field rather than a misleading growth rate. Margin QoQ/YoY compares single-quarter margins.
- `roe_quarterly_approx = net_income_single / average equity × 100`. When prior-quarter equity is unavailable, it falls back to ending equity.
- `debt_ratio = total_liabilities / total_assets × 100`.
- FinMind cash-flow values are treated as year-to-date. The previous quarter's year-to-date value is subtracted to obtain quarterly operating cash flow and capital expenditure. A raw capital expenditure outflow may be negative; its magnitude is stored as a **positive spending amount**. `free_cash_flow = operating_cash_flow - capital_expenditure`. Missing inputs remain empty.

The program maps FinMind `type` fields into stable CSV column names. It uses `TaiwanStockMonthRevenue`, `TaiwanStockFinancialStatements`, `TaiwanStockBalanceSheet`, and `TaiwanStockCashFlowsStatement`.

## Incremental updates and API budget

On the first run, selected stocks are fetched from 2024-01-01 to provide prior periods for YoY metrics. Later runs start at the last locally stored revenue date or quarter-end report date, retaining one period of overlap to accept corrections. Yearly files use `stock_id + year + month` and `stock_id + year + quarter` as unique keys; revised source values replace stored values.

FinMind requests have a 20-second timeout and at most three attempts. Every HTTP attempt, including retries, is counted against a local rolling-hour ceiling of **500 requests**. The count is stored in an ignored local budget file under `data/`; no token is stored there. At the ceiling, requests stop and already obtained CSV records remain saved. The local ceiling does not read FinMind's account-wide quota, so other clients using the same token may consume additional allowance.

FinMind data and derived CSVs remain local under `data/revenue/` and `data/financials/`; these directories are ignored by Git. FinMind's data terms do not permit redistributing raw data, so the repository contains the code to regenerate the CSVs rather than the fetched records. Source: [FinMind API and usage reference](https://finmind.github.io/llms-full.txt).

## Phase 4: local factors and QGM

Run `python src/main.py factors` to read existing stock, price, revenue, and financial CSVs. This command makes **no network or FinMind API requests**. It writes one row per stock to `data/factors/latest.csv` and the top 200 ranked rows to `data/results/latest.csv` and `data/results/latest.json`. All three outputs remain local and are ignored by Git because they include FinMind-derived values.

Price windows count **trading rows**, not calendar days. `ma20`, `ma60`, `ma120`, and average volume use the latest 20/60/120 rows; `return_20d`, `return_60d`, and `return_120d` compare the latest close with the close 20/60/120 trading rows earlier. Returns and distance from the 60-day high are percentage numbers. A missing window stays empty. Revenue's three-month average and positive count require three consecutive months with YoY values. `eps_ttm` and the four-quarter EPS counts require four consecutive quarters with the relevant values. TTM sums FinMind **single-quarter** EPS; due to share-count adjustments it may differ from a published cumulative EPS.

The first-version QGM schedule totals 100 points. Missing score inputs receive zero points while remaining empty in the factor columns. `data_completeness` is the percentage of the 21 score inputs with usable numbers; it is not a score multiplier. Ties sort by Growth, Quality, Momentum, then stock ID.

| Category | Factor | Points |
| --- | --- | --- |
| Quality (40) | Quarterly approximate ROE | ≥20: 10; ≥15: 8; ≥10: 6; ≥5: 3 |
| | Single-quarter gross margin | ≥40: 6; ≥25: 4; ≥15: 2 |
| | Single-quarter operating margin | ≥20: 6; ≥10: 4; ≥5: 2 |
| | Debt ratio | ≤30: 6; ≤45: 4; ≤60: 2 |
| | Single-quarter operating cash flow and FCF | 3 each when positive |
| | Positive EPS in last four quarters | 4 quarters: 6; 3: 4; 2: 2 |
| Growth (35) | Latest monthly revenue YoY | ≥30: 10; ≥20: 8; ≥10: 6; ≥0: 3 |
| | Three-month revenue YoY average | ≥20: 5; ≥10: 4; ≥0: 2 |
| | Single-quarter EPS YoY | ≥50: 10; ≥30: 8; ≥15: 6; ≥0: 3 |
| | Single-quarter gross-margin YoY change, percentage points | ≥3: 5; ≥1: 4; ≥0: 2 |
| | Single-quarter operating-margin YoY change, percentage points | ≥3: 5; ≥1: 4; ≥0: 2 |
| Momentum (25) | Close above MA20, MA60, MA120 | 3, 4, 4 respectively |
| | 20-trading-day return | ≥10: 4; ≥5: 3; ≥0: 1 |
| | 60-trading-day return | ≥20: 5; ≥10: 4; ≥0: 2 |
| | Average volume 20 > average volume 60 | 2 |
| | Distance to 60-day high | ≥−2: 3; ≥−5: 2; ≥−10: 1 |

All thresholds are initial parameters for later backtesting. No valuation, institutional-investor, or forecast factor is included in this phase.

## Phase 4.1: limited historical market update

Run a bounded, official **all-market daily** backfill:

```powershell
python src/main.py market-history --start 2026-09-14 --end 2026-10-14
python src/main.py factors
```

The history command uses TWSE `https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX` and TPEx `https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes`. These are date-specific JSON datasets covering the whole respective market. No verified all-market monthly OHLCV endpoint is used, and the command never requests one stock at a time. It does not call FinMind.

Each HTTP attempt is counted and followed by at least one second of rest. Transient 403, 5xx, timeout, and connection errors back off by 2, 5, then 10 seconds, with at most three retries; 429 immediately stops that source for the run. Repeated failure also stops that source while keeping successfully saved dates. Existing market dates and recorded past no-data dates are skipped on rerun. A single command is capped at 36 calendar days, so longer history requires an explicit later run. Yearly price files are merged by `date + stock_id` and replaced atomically after writing a temporary file. A temporarily busy CSV gets the same delayed write retries without making extra HTTP requests.

The Stage 1 window contains 20 trading days in the local data. That is enough for MA20 and 20-day average volume; `return_20d` needs the latest close **plus** a close 20 trading days earlier (21 observations) and therefore remains empty. The command does not fetch earlier dates automatically.

### Stage 2: extend to roughly three months

Run the bounded history command in three non-overlapping chunks, then recalculate factors:

```powershell
python src/main.py market-history --start 2026-07-01 --end 2026-07-31
python src/main.py market-history --start 2026-08-01 --end 2026-08-31
python src/main.py market-history --start 2026-09-01 --end 2026-09-13
python src/main.py factors
```

The updater skips dates already present in the yearly CSV and cached past no-data dates. Repeating these three commands after a successful run makes zero HTTP requests. This Stage 2 snapshot spans 2026-07-01 through 2026-10-14 and has 72 trading days for 2330, 2317, and 2454; it supports MA60 and 20/60-trading-day returns. MA120 still requires more history and is left empty. Do not automatically extend the range when a factor lacks enough observations.

## Phase 5A: configurable strategies and GitHub Pages

`config/strategies.json` is the shared source of default selection rules. It contains the data universe, QGM weights and every tier threshold, homepage score filters, and individually enabled conditions for strategies A–E. `src/strategy_engine.py` and `docs/engine.mjs` interpret the same JSON structure. Missing numeric inputs result in `missing_data`; missing institutional or dividend source fields result in `unavailable`. A strategy passes only when every enabled condition has data and passes.

`python src/main.py factors` recalculates factors from existing local files and now also builds `docs/data/latest.json` and copies the strategy defaults to `docs/config/strategies.json`. `python src/main.py pages` rebuilds only the Pages files from an existing `data/factors/latest.csv`. Neither command calls FinMind, TWSE, or TPEx. The Pages JSON contains a selected set of factor values and statuses for all listed stocks; local revenue and financial statement rows are not copied into it. Configure GitHub Pages to publish `/docs` from `main` if it is not already set up.

The browser calculates QGM and all strategy statuses again when a user changes settings. Settings are kept in that browser's `localStorage`; they are never written back to GitHub. Import and export move JSON files only between the browser and the user's computer. Changing the price floor below the downloaded fundamentals universe or including financials triggers a coverage warning. The current local history supports PER from price and TTM EPS, but PBR and three complete financial years are unavailable for strategy C. The 60-day market comparison in strategy B uses the equal-weight average of available local stock returns as a disclosed market proxy. Strategies D and E remain unavailable until institutional and dividend data are supplied.


## Phase 5B: official valuation and dividend data

Run `python src/main.py valuation` and `python src/main.py dividends` separately, or run `python src/main.py phase5b` to update both, recalculate local factors, and rebuild Pages. `valuation` stores one row per `date + stock_id` under `data/valuation/YYYY.csv`; annual dividend rows are consolidated by `stock_id + year` in `data/dividends/history.csv`. Existing keys are replaced by newer source data. Requests use a 20-second timeout, up to three attempts with backoff, and a one-second pause between market sources.

Annual dividend `year` is the official `股利年度` (earnings/distribution attribution year), converted from ROC to Gregorian year; it is not the cash payment year. For example, a 2025 (`114`) earnings-year distribution can be reported or paid in 2026. Annual cash dividend sums earnings distributions and cash paid from statutory reserve and capital reserve. Stock dividend sums the three official stock-distribution fields; total dividend is their per-share sum. Annual EPS is the sum of four locally stored single-quarter EPS values only when all four quarters exist. Payout ratio stays empty when annual EPS is zero, negative, or unavailable. `dividend_years_5` counts positive-dividend years in the latest five-year window; an explicit zero-dividend source row counts as known data but not as a dividend year. A missing row or null cash-dividend value remains missing. `dividend_history_years_available` counts years with a non-null cash-dividend value. Three-year CAGR needs four consecutive annual observations with positive dividends. The non-decreasing test reports the smallest year-over-year percentage change over that period; Strategy E's condition threshold defaults to −5%, and its enabled switch is the user-facing boolean.

Each strategy has its own completeness field (`strategy_a_data_completeness` through `strategy_e_data_completeness`), calculated from that strategy's enabled conditions only. Strategy C depends on ROE, three-year positive EPS and operating-cash-flow year counts, debt ratio, PER, and PBR; dividend fields do not affect its completeness. Strategy E depends on five-year dividend years, yield, payout ratio, three-year dividend growth, the non-decreasing test, and free cash flow. QGM `data_completeness` remains separate and unchanged. The current local official dividend history has rows for attribution year 2021 (21 stocks) and 2025 (1,969 stocks), but no 2022–2024 rows; those missing years are not inferred as zero. The current local fundamentals files contain full-quarter annual records only for 2024 and 2025, so Strategy C's three-year EPS and operating-cash-flow checks remain missing until another complete year is available. These fields are summaries only; historical dividend rows are not copied into `docs/data/latest.json`.

Sources: [TWSE daily valuation](https://www.twse.com.tw/zh/trading/historical/bwibbu.html), [TWSE listed-company dividend distribution](https://openapi.twse.com.tw/v1/opendata/t187ap45_L), [TPEx valuation](https://www.tpex.org.tw/zh-tw/market-trade.html), and [TPEx dividend distribution CSV](https://mopsfin.twse.com.tw/opendata/t187ap45_O.csv). The dividend datasets are free government open data. QGM formulas and the 100-point total remain unchanged; these new fields are used only by strategy conditions.

Run `python -m unittest discover -s tests -p 'test_*.py'` and `node --test tests/test_frontend.mjs` to check both engines, their shared fixture, missing-value behavior, and browser-state helpers. The CI workflow runs both suites.
