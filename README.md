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

- `gross_margin = gross_profit / revenue × 100` and `operating_margin = operating_income / revenue × 100`.
- `gross_margin_qoq`, `gross_margin_yoy`, `operating_margin_qoq`, and `operating_margin_yoy` are **percentage-point differences**.
- `eps_qoq` and `eps_yoy` are growth percentages. A zero, missing, or negative comparison EPS produces an empty field rather than a misleading growth rate.
- `roe = quarterly net_income / average equity × 100`. When prior-quarter equity is unavailable, the first version falls back to ending equity. This quarterly ROE is not annualized; the fallback can later be replaced with average equity once more history is available.
- `debt_ratio = total_liabilities / total_assets × 100`.
- FinMind cash-flow values are treated as year-to-date. The previous quarter's year-to-date value is subtracted to obtain quarterly operating cash flow and capital expenditure. A raw capital expenditure outflow may be negative; its magnitude is stored as a **positive spending amount**. `free_cash_flow = operating_cash_flow - capital_expenditure`. Missing inputs remain empty.

The program maps FinMind `type` fields into stable CSV column names. It uses `TaiwanStockMonthRevenue`, `TaiwanStockFinancialStatements`, `TaiwanStockBalanceSheet`, and `TaiwanStockCashFlowsStatement`.

## Incremental updates and API budget

On the first run, selected stocks are fetched from 2024-01-01 to provide prior periods for YoY metrics. Later runs start at the last locally stored revenue date or quarter-end report date, retaining one period of overlap to accept corrections. Yearly files use `stock_id + year + month` and `stock_id + year + quarter` as unique keys; revised source values replace stored values.

FinMind requests have a 20-second timeout and at most three attempts. Every HTTP attempt, including retries, is counted against a local rolling-hour ceiling of **500 requests**. The count is stored in an ignored local budget file under `data/`; no token is stored there. At the ceiling, requests stop and already obtained CSV records remain saved. The local ceiling does not read FinMind's account-wide quota, so other clients using the same token may consume additional allowance.

FinMind data and derived CSVs remain local under `data/revenue/` and `data/financials/`; these directories are ignored by Git. FinMind's data terms do not permit redistributing raw data, so the repository contains the code to regenerate the CSVs rather than the fetched records. Source: [FinMind API and usage reference](https://finmind.github.io/llms-full.txt).
