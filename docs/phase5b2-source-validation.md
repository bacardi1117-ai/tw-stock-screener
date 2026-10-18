# Phase 5B.2 Stage 1 source validation — 2026-10-17

Status: stopped at the user-required per-stock source decision gate. No 899-stock expansion, production history replacement, strategy regeneration, commit, or push has been performed. Phase 5B.2 is not complete.

## Source capability

| Probe | Rows / unique companies | Observed years | Historical year parameter |
|---|---:|---|---|
| TWSE t187ap06_L_ci | 1050 / 1050 | ROC 115 | Not exposed in OpenAPI |
| TPEx mopsfin_t187ap06_O_ci | 885 / 885 | ROC 115 | Not exposed in OpenAPI |
| TWSE t187ap45_L | 1230 / 1113 | ROC 114,115 | Not exposed in OpenAPI |
| TPEx t187ap45_O.csv | 964 / 893 | ROC 114,115 | Static download |
| MOPS landing page | Security restriction page, HTTP 200 | Not verified | Not verified |
| FinMind sample | One stock and one dataset per request | Requested histories available | start_date |

These probes do not prove that no official historical bulk source exists. No usable historical bulk source was validated in this run. The TPEx response also had incorrectly decoded Chinese field names in the initial probe; English code/year keys remained readable. Production ingestion must decode the response correctly.

Official endpoints: https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci ; https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci ; https://openapi.twse.com.tw/v1/opendata/t187ap45_L ; https://mopsfin.twse.com.tw/opendata/t187ap45_O.csv . Schema: https://openapi.twse.com.tw/v1/swagger.json and https://www.tpex.org.tw/openapi/swagger.json . FinMind documentation: https://finmind.github.io/tutor/TaiwanMarket/Fundamental/ .

## Annual EPS sample (NTD/share)

| Stock | 2023 reported annual EPS | 2024 reported annual EPS | 2025 reported annual EPS | FinMind sum of quarterly EPS, 2023/24/25 |
|---|---:|---:|---:|---|
| 2330 TSMC | 32.34 | 45.25 | 66.26 basic | 32.34 / 45.26 / 66.26 |
| 2317 Hon Hai | 10.25 | 11.01 | 13.61 | 10.25 / 11.01 / 13.60 |
| 2454 MediaTek | 48.51 | 66.92 | 66.16 | 48.51 / 66.92 / 66.17 |

Quarterly EPS sums are not an exact substitute for reported annual EPS. The historical annual EPS ingestion method still needs resolution before production integration. TSMC 2025 diluted EPS is 66.25; do not mix basic and diluted series.

Issuer sources:
- TSMC 2025 consolidated statements, basic/diluted EPS and annual OCF: https://investor.tsmc.com/sites/ir/financial-report/2025/TSMC%202025Q4%20Consolidated%20Financial%20Statements_E_1.pdf
- TSMC 2023 annual report: https://investor.tsmc.com/static/annualReports/2023/english/index.html
- Hon Hai 2023: https://www.honhai.com/en-us/press-center/events/foxconn-events/1299
- Hon Hai 2024: https://www.honhai.com/zh-tw/press-center/events/csr-events/1553
- Hon Hai 2025 announcement listed at https://www.honhai.com/en-us/press-center/press-releases/latest-news?category=Monthly+Revenues
- MediaTek 2023: https://corp.mediatek.com/investor-relations/investor-relation-news/2023-q4-financial-results
- MediaTek 2024: https://corp.mediatek.com/investor-relations/investor-relation-news/2024-q4-financial-results
- MediaTek 2025: https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Quarterly%20Earnings%20Release/2025/Quarterly%20Earnings%20Release-2025Q4/Press%20Release.pdf?hsLang=en

## FinMind annual OCF sample (NTD)

December 31 cumulative operating cash flow is used, not a single-quarter flow and not the sum of four cumulative quarters. TSMC 2024/25 values agree with the issuer's annual cash-flow statement after converting thousands of NTD to NTD. Other sample values below are dataset observations, not all independently reconciled to issuer reports.

| Stock | 2023 | 2024 | 2025 |
|---|---:|---:|---:|
| 2330 | 1,241,967,347,000 | 1,826,177,068,000 | 2,274,975,625,000 |
| 2317 | 445,552,717,000 | 166,028,839,000 | 226,852,474,000 |
| 2454 | 166,091,322,000 | 156,054,607,000 | 162,792,872,000 |

## FinMind cash dividend sample (NTD/share)

Year means earnings attribution year parsed from the dataset year field, never payment date. Cash includes earnings distribution and cash statutory surplus; stock dividend components are zero for these sample periods. TSMC has four quarterly records per year; Hon Hai one annual record; MediaTek annual records for 2021/22 and two half-year records for 2023/24/25.

| Stock | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| 2330 | 11 | 10.99964144 | 12.99957938 | 16.99981610 | 22.00010018 |
| 2317 | 5.2 | 5.3 | 5.4 | 5.79998376 | 7.17179227 |
| 2454 | 73.00106040 | 76.00660606 | 55.00530874 | 54.00021747 | 53.50021529 |

The existing 2330 2025 value near 6 covers Q4 only; the existing MediaTek value near 24.5 covers H2 only. Neither is a full annual cash dividend. Hon Hai's announced 2025 dividend 7.2 differs from the adjusted per-share FinMind value 7.17179227; a production merge needs explicit source/revision precedence. Do not overwrite higher-quality existing rows blindly. Missing periods must remain unknown; never infer zero from absent rows.

## Requests and expansion cost

- FinMind: exactly 9 requests, 3 datasets per stock, all HTTP 200. No 429, 403, or timeout. Summed measured request time: 1.236 seconds (small sample, not a throughput promise).
- Official probes: 7 HTTP responses, all 200; MOPS response was a security block. Before network permission, 3 ConnectionError attempts failed without an HTTP response. Browser research requests are separate from this ingestion ledger.
- 899 stocks: 2,697 requests total; 2,688 additional if these three cached samples are reused.
- 1,982 stocks: 5,946 requests total; 5,937 additional if samples are reused.
- At 400 calls per hourly window: at least 7 windows for 899, 15 for 1,982. Approximately 6–7 hours or 14–15 hours respectively with hourly scheduling, excluding retries, shared quota consumption, and additional annual EPS validation requests. The 3-request estimate does not solve the exact annual EPS discrepancy.
- Existing FinMind client, retry, budget and a separate resumable sample progress file are used. The sample fetcher has a fixed three-stock allowlist and a 30-call run ceiling. No fundamentals batch/exception queue changes.

## Current production state and remaining work

Existing docs/data/latest.json still reports C: 0 judgeable / 0 pass and E: 0 judgeable / 0 pass (1,982 missing_data for each). These are unchanged pre-integration counts, not post-fix results.

Sample cache structural validation passed: nine completed jobs, three years of four EPS quarters and one year-end OCF record per sample, and complete expected dividend periods for five years. Full requested strategy regression tests and Python/JS parity tests have not been implemented or run for Phase 5B.2. Production annual history, factor integration, merge protections, README semantics and final regression tests remain pending the source/expansion decision. No commit or push: user requires validated data and successful implementation tests first.
