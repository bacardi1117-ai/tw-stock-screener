# 官方證據與歷史資料本機修復

修復完成時間：2026-10-18T09:15:44+00:00。本次未提交、未推送、未部署；FinMind API calls = 0。

## 修復範圍與口徑

- 年度 EPS 一律為 1/1～12/31 基本每股盈餘、元／股；同家公司三年維持相同報表口徑，不混入稀釋 EPS 或半年累計 EPS。
- 股利 year 代表盈餘歸屬年度，不是發放年度。現金、股票成分獨立核對；完整 A、H1/H2、Q1/Q2/Q3/Q4 保留既有無重疊解析；混合、缺期及零值補入需要逐年官方證據。
- 全年與分期同一成分不相加。明確官方零值才能補 0；未回傳、期間不足、年度涵蓋未確認，均保持缺值或未確認旗標。
- 保留已有的有效觀測值；未確認全年涵蓋的舊快照不得視為完整年度。來源矛盾即使有數值也不認定完整。
- 共用 data/.history_batch_guard.lock，取得鎖後才讀取最新 progress；先備份，再逐支寫入。沒有呼叫 history-batch，沒有啟動額外抓取程序。
- 原每小時排程與 API/retry 限制不變。批次發布只允許四個既有資料輸出，避免將未審閱程式、證據與測試夾帶到自動提交。

## 本次補入與修正

- 2408：2023、2024 年現金及股票股利確認為零；2025 官方 1.5 元與快取 1.34714912 元尚有口徑差異，保留原觀測，年度完整旗標改為 false，整支仍待核對。
- 2426：2021 H1 明確零股利，與 H2 現金 1 元合併；2022 全年明確零股利。
- 2301：2025 Q1、Q3 明確零股利，加 Q2 2 元、Q4 3 元，全年現金 5 元；2021～2024 缺期證據仍不足。
- 2474：2021、2022 以公司年度股利表確認涵蓋；2021 保留快取精度 10.21394967，與官方顯示 10.21 在二位小數精度內一致，不捏造 H1=0。
- 2753：2025 現金 H1 4 元 + H2 7.5 元 = 11.5 元，股票 0.5 元；全年股票記錄與半年現金記錄分開核對，總股利 12 元，不重複相加。
- 共補齊 8 個股利年度的缺值或年度涵蓋；6 個年度由缺值補成金額，另外 2 個原本只有分期快照，改為確認全年。另保留 2408 的一個來源衝突年度。
- 正式年度 EPS 核對 15 筆：補入 8 個缺值，修正 4 個季度加總值；其餘 3 筆金額相符。
- 變成 completed 的 6 支：2248 華勝-KY、2426 鼎元、2474 可成、2753 八方雲集、3135 凌航、3158 嘉實。

## 官方年度基本 EPS

| 股票 | 報表口徑 | 2023 | 2024 | 2025 |
|---|---|---:|---:|---:|
| 2248 華勝-KY | 合併 | 3.29 | 6.42 | 5.32 |
| 2751 王座 | 合併 | 6.83 | 4.55 | 4.57 |
| 2762 世界健身-KY | 合併 | 3.50 | 3.19 | 3.75 |
| 3135 凌航 | 公司本身財務報告（standalone） | 1.30 | 2.37 | 6.33 |
| 3158 嘉實 | 合併 | 5.91 | 7.32 | 7.27 |

年度原報或查核比較數來源與頁碼如下；來源檔 SHA-256、核對日期與基本／年度／幣別皆保存於 annual_eps_verified.json。2248 掃描頁已人工目視核對；3158 的 2024 下載檔無法解析，因此使用 2025 查核財報之 2024 比較欄，2023 使用當年度原報。

- 2248 2023：[官方財報](https://doc.twse.com.tw/pdf/202404_2248_AI1_20261018_170431.pdf)，PDF 第 9 頁，查核比較欄。
- 2248 2024：[官方財報](https://doc.twse.com.tw/pdf/202504_2248_AI1_20261018_170429.pdf)，PDF 第 45 頁，查核比較欄。
- 2248 2025：[官方財報](https://doc.twse.com.tw/pdf/202504_2248_AI1_20261018_170429.pdf)，PDF 第 45 頁，當年度欄。
- 2751 2023：[官方財報](https://s3.ap-northeast-1.wasabisys.com/cdn.kingza.com.tw/2025/04/113%E5%B9%B4_Q4%E7%8E%8B%E5%BA%A7%E8%B2%A1%E5%A0%B1.pdf)，PDF 第 41 頁，查核比較欄。
- 2751 2024：[官方財報](https://s3.ap-northeast-1.wasabisys.com/cdn.kingza.com.tw/2026/06/%E7%8E%8B%E5%BA%A7114-Q4%E4%B8%AD%E6%96%87.pdf)，PDF 第 45 頁，查核比較欄。
- 2751 2025：[官方財報](https://s3.ap-northeast-1.wasabisys.com/cdn.kingza.com.tw/2026/06/%E7%8E%8B%E5%BA%A7114-Q4%E4%B8%AD%E6%96%87.pdf)，PDF 第 45 頁，當年度欄。
- 2762 2023：[官方財報](https://investor.worldgymtaiwan.com/files/uploads/Financial%20Reports/202404_2762_CH.pdf)，PDF 第 11 頁，查核比較欄。
- 2762 2024：[官方財報](https://investor.worldgymtaiwan.com/files/uploads/Financial%20Reports/202504_2762_CH.pdf)，PDF 第 10 頁，查核比較欄。
- 2762 2025：[官方財報](https://investor.worldgymtaiwan.com/files/uploads/Financial%20Reports/202504_2762_CH.pdf)，PDF 第 10 頁，當年度欄。
- 3135 2023：[官方財報](https://www.goldkey.com.tw/_i/assets/file/report/b4ba2a3d924084ab2b67907eaab8c4e9.pdf)，PDF 第 40 頁，查核比較欄。
- 3135 2024：[官方財報](https://www.goldkey.com.tw/_i/assets/file/report/639664659b603ae39c0ed461e76c9586.pdf)，PDF 第 45 頁，查核比較欄。
- 3135 2025：[官方財報](https://www.goldkey.com.tw/_i/assets/file/report/639664659b603ae39c0ed461e76c9586.pdf)，PDF 第 45 頁，當年度欄。
- 3158 2023：[官方財報](https://www.sysjust.com.tw/Finance/112Q4%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf)，PDF 第 11 頁，當年度欄。
- 3158 2024：[官方財報](https://www.sysjust.com.tw/Finance/2025Q4%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf)，PDF 第 11 頁，查核比較欄。
- 3158 2025：[官方財報](https://www.sysjust.com.tw/Finance/2025Q4%E5%90%88%E4%BD%B5%E8%B2%A1%E5%A0%B1.pdf)，PDF 第 11 頁，當年度欄。

## 完整度與策略（不改門檻）

| 指標 | 修復前 | 修復後 |
|---|---:|---:|
| 三年 EPS 完整（全市場） | 233 | 238 |
| 三年 OCF 完整（全市場） | 240 | 240 |
| 五年股利完整（全市場） | 175 | 178 |
| 策略 C 通過（eligible 899） | 1 | 1 |
| 策略 C 可判斷未通過（eligible 899） | 218 | 223 |
| 策略 C 缺資料無法判斷（eligible 899） | 680 | 675 |
| 策略 E 通過（eligible 899） | 5 | 5 |
| 策略 E 可判斷未通過（eligible 899） | 159 | 161 |
| 策略 E 缺資料無法判斷（eligible 899） | 735 | 733 |

完成 171 → 177；remaining 728 → 722。其中待核對失敗 63（no_data 45、unsupported_format 18）、retryable 68、尚未嘗試 591。這是包含後續排程新增進度的最新全量狀態，不是先前 49 支舊名單的單獨統計。

## 剩餘原因

逐股、逐年、欄位與來源見 data/state/history_official_remaining_fields.csv。分類可重疊，不可相加當成股票總數。

| 原因 | 股票數 | 年度欄位項目數 |
|---|---:|---:|
| 快取來源未回傳該年度 | 39 | 83 |
| 分期不足或全年／分期重疊 | 21 | 70 |
| 已有快照金額但全年涵蓋未確認 | 23 | 23 |
| 年度 EPS 不足 | 2 | 5 |
| 跨來源金額口徑衝突 | 1 | 1 |

- 2751：股利 2021、2022 來源未回傳，2024 只有 H2。
- 2762：股利 2021、2022 來源未回傳；2024 只有 Q3/Q4，2025 只有 Q2/Q3/Q4。既有最新金額不能代替完整年度證據。
- 2301：股利 2021～2024 缺 Q1/Q3 的官方零值或其他完整性證據。
- 2408：2025 現金股利跨來源差異，保留數值與待核對標記，沒有強制完成。
- 後續批次的 3467 台灣精材仍缺 EPS 2023、2024；3485 敘豐仍缺 EPS 2023～2025。OCF 在這些失敗快取中沒有新增缺年。

## 驗證與修改檔案

Python 全套 101 項測試通過（0 失敗），含零股利、半年配、季配、全年／分期重疊、現金／股票獨立成分、原成功案例、EPS 口徑、鎖定、進度保留及來源衝突不得完成。

- 與修復前備份比較：其他股票資料金額與 progress 紀錄完全保留，最後 API 批次統計與 last_attempt_at 沒有改寫。
- 原 171 支成功快取，與 HEAD 版本解析的 EPS、OCF、現金、股票、總股利、payout、完整旗標逐筆相同。2330、2317、2454 另有可在 CI 執行的小型回歸 fixture。
- 全市場 1,982 支 Quality/Growth/Momentum/Total 與 QGM 完整度和修復前一致。config/strategies.json 未修改。
- 本機已重新執行 python src/main.py factors 並重建 docs/data/latest.json；沒有部署正式站。

新增：src/dividend_coverage.py、src/repair_history_official.py、tests/test_history_official.py、tests/fixtures/history_success_cases.json、data/state/dividend_verified.json、data/state/history_official_repair_report.json、data/state/history_official_repair_changes.csv、data/state/history_official_remaining_fields.csv、本報告。

修改：src/history_batch.py、src/update_dividends.py、data/state/annual_eps_verified.json、data/annual_financials/history.csv、data/dividends/history.csv、data/state/history_progress.json、data/state/history_official_validation.json、docs/data/latest.json。

上一階段本機驗證時未提交或推送。此次依使用者授權提交修復與最新必要資料；既存其他診斷報告不納入。

## 授權發布前最新狀態

快照重建時間：2026-10-18T10:03:41+00:00。共用排程鎖內讀取最新進度，progress 逐位元保留，沒有重跑修復、沒有啟動補抓，FinMind API 為 0 次。

修復後的每小時批次另完成 44 支；連同先前尚未提交的 40 支正常批次進度，completed 為 221、remaining 為 678。待核對 failed 79、retryable 68。上方歷史表格為原修復事件的統計，逐年缺漏 CSV 已刷新至此最新狀態。

最新全市場：三年 EPS 297、三年 OCF 299、五年股利 222。eligible 899 支中，C 可判斷 277／通過 1；E 可判斷 202／通過 7。

南亞科 2025 股利仍保留觀測值 1.34714912，官方參考值 1.5；annual_complete=false、source_review_required=true、progress 仍為 failed 待核對。沒有強制改值或完成。

既有 ACTIVE 每小時排程保留（每小時第 40 分）；沿用同一本機專案的 history-batch CLI 與共享鎖。提交包含 parser、成分合併模組與官方證據檔，後續新程序會載入修正版；沒有新增排程或第二個抓取程序。
