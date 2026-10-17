export const FIELD_LABELS = {
  roe: { label: 'ROE', unit: '%', description: '目前使用季度 ROE 近似值。' },
  roe_quarterly_approx: { label: '季度 ROE（近似值）', unit: '%', description: '以目前可取得的季度財報近似計算。' },
  gross_margin: { label: '毛利率', unit: '%' },
  gross_margin_single: { label: '單季毛利率', unit: '%' },
  operating_margin: { label: '營業利益率', unit: '%' },
  operating_margin_single: { label: '單季營業利益率', unit: '%' },
  debt: { label: '負債比', unit: '%' },
  debt_ratio: { label: '負債比', unit: '%' },
  ocf: { label: '營業現金流', unit: '元' },
  operating_cash_flow_single: { label: '單季營業現金流', unit: '元' },
  fcf: { label: '自由現金流', unit: '元' },
  free_cash_flow_single: { label: '單季自由現金流', unit: '元' },
  eps_stability: { label: 'EPS 穩定度', description: '最近四季中 EPS 為正的季度數。' },
  eps_positive_quarters_4: { label: '最近四季正 EPS 季數', unit: '季', description: '最近四季中 EPS 為正的季度數。' },
  revenue_yoy: { label: '最新月營收年增率', unit: '%', description: '最新月份營收相較去年同期的成長率。' },
  revenue_3m: { label: '近 3 月營收年增率平均', unit: '%' },
  revenue_yoy_3m_avg: { label: '近 3 月營收年增率平均', unit: '%' },
  eps_yoy: { label: 'EPS 年增率', unit: '%' },
  eps_ttm: { label: 'EPS TTM', unit: '元' },
  gross_margin_yoy: { label: '毛利率年增變化', unit: '百分點', description: '使用百分點差，而非百分比成長率。' },
  operating_margin_yoy: { label: '營業利益率年增變化', unit: '百分點', description: '使用百分點差，而非百分比成長率。' },
  above_ma20: { label: '股價高於 20 日均線', description: '最新股價大於 MA20。' },
  above_ma60: { label: '股價高於 60 日均線', description: '最新股價大於 MA60。' },
  above_ma120: { label: '股價高於 120 日均線', description: '最新股價大於 MA120。' },
  return_20d: { label: '20 日報酬率', unit: '%', description: '最近 20 個交易日的價格報酬率。' },
  return_60d: { label: '60 日報酬率', unit: '%' },
  return_120d: { label: '120 日報酬率', unit: '%' },
  return_60d_vs_market: { label: '60 日相對市場報酬', unit: '百分點', description: '個股 60 日報酬率減去本地全市場等權平均報酬率。' },
  eps_positive_years: { label: 'EPS 為正的完整年度數', unit: '年' },
  operating_cash_flow_positive_years: { label: '營業現金流為正的完整年度數', unit: '年' },
  foreign_plus_trust_20d: { label: '外資＋投信 20 日累計買賣超' },
  trust_10d: { label: '投信 10 日累計買賣超' },
  avg_volume_20: { label: '20 日平均成交量', unit: '股' },
  avg_volume_60: { label: '60 日平均成交量', unit: '股' },
  dividend_years: { label: '連續配息年度數', unit: '年' },
  dividend_yield: { label: '現金股利殖利率', unit: '%' },
  payout_ratio: { label: '現金股利配息率', unit: '%' },
  volume_20_gt_60: { label: '20 日均量高於 60 日均量', description: '20 日平均成交量大於 60 日平均成交量。' },
  avg_volume_20_gt_60: { label: '20 日均量高於 60 日均量', description: '20 日平均成交量大於 60 日平均成交量。' },
  distance_high: { label: '距 60 日高點', unit: '%', description: '0% 代表位於 60 日高點；-5% 代表距高點 5%。' },
  distance_to_60d_high: { label: '距 60 日高點', unit: '%', description: '0% 代表位於 60 日高點；-5% 代表距高點 5%。' },
  per: { label: '本益比（PER）' },
  pbr: { label: '股價淨值比（PBR）' },
  score_total: { label: 'QGM 總分', unit: '分' },
  score_quality: { label: 'Quality 品質分數', unit: '分' },
  score_growth: { label: 'Growth 成長分數', unit: '分' },
  score_momentum: { label: 'Momentum 動能分數', unit: '分' },
  score_total_min: { label: '最低 QGM 總分', unit: '分' },
  score_quality_min: { label: '最低 Quality 分數', unit: '分' },
  score_growth_min: { label: '最低 Growth 分數', unit: '分' },
  score_momentum_min: { label: '最低 Momentum 分數', unit: '分' },
  data_completeness_min: { label: '最低資料完整度', unit: '%' },
  min_price: { label: '最低股價', unit: '元' },
  search: { label: '股票代碼 / 名稱' },
  sort: { label: '排序' },
  sort_direction: { label: '順序' },
  stock_rank: { label: '排名' },
  stock_id: { label: '代碼' },
  stock_name: { label: '名稱' },
  close: { label: '股價', unit: '元' },
  ma20: { label: 'MA20', unit: '元' },
  ma60: { label: 'MA60', unit: '元' },
  ma120: { label: 'MA120', unit: '元' },
  operating_margin_short: { label: '營益率', unit: '%' },
  data_completeness: { label: '資料完整度', unit: '%' },
  strategy_a: { label: '策略 A｜低估成長' },
  strategy_b: { label: '策略 B｜強勢成長' },
  strategy_c: { label: '策略 C｜高品質便宜' },
  strategy_d: { label: '策略 D｜法人＋動能' },
  strategy_e: { label: '策略 E｜股息成長' },
  quality: { label: 'Quality 品質因子' },
  growth: { label: 'Growth 成長因子' },
  momentum: { label: 'Momentum 動能因子' },
};

export const RULE_LABELS = {
  roe: 'ROE',
  gross_margin: '毛利率',
  operating_margin: '營業利益率',
  debt: '負債比',
  ocf: '營業現金流',
  fcf: '自由現金流',
  eps_stability: 'EPS 穩定度',
  revenue_yoy: '最新月營收年增率',
  revenue_3m: '近 3 月營收年增率平均',
  eps_yoy: 'EPS 年增率',
  gross_margin_yoy: '毛利率年增變化',
  operating_margin_yoy: '營業利益率年增變化',
  above_ma20: '股價高於 20 日均線',
  above_ma60: '股價高於 60 日均線',
  above_ma120: '股價高於 120 日均線',
  return_20d: '20 日報酬率',
  return_60d: '60 日報酬率',
  volume_20_gt_60: '20 日均量高於 60 日均量',
  distance_high: '距 60 日高點',
  latest_revenue_yoy: '最新月營收年增率',
  revenue_yoy_3m_avg: '近 3 月營收年增率平均',
  price_above_ma20: '股價高於 20 日均線',
  price_above_ma60: '股價高於 60 日均線',
  price_above_ma120: '股價高於 120 日均線',
  ma60_above_ma120: '60 日均線高於 120 日均線',
  avg_volume_20_gt_60: '20 日均量高於 60 日均量',
  return_60d_vs_market: '60 日相對市場報酬',
  operating_cash_flow_positive: '營業現金流為正',
  free_cash_flow_positive: '自由現金流為正',
  eps_growth: 'EPS 年增率',
  eps_positive_years: 'EPS 為正的完整年度數',
  operating_cash_flow_positive_years: '營業現金流為正的完整年度數',
  foreign_plus_trust_20d: '外資＋投信 20 日累計買賣超',
  trust_10d: '投信 10 日累計買賣超',
  dividend_years: '連續配息年度數',
  dividend_yield: '現金股利殖利率',
  payout_ratio: '現金股利配息率',
};

export const OPERATOR_LABELS = {
  gt: '大於',
  gte: '至少',
  lt: '小於',
  lte: '不高於',
  eq: '等於',
};

export const STRATEGY_LABELS = {
  strategy_a: '低估成長',
  strategy_b: '強勢成長',
  strategy_c: '高品質便宜',
  strategy_d: '法人＋動能',
  strategy_e: '股息成長',
};

export function fieldLabel(key, fallback = key) {
  return FIELD_LABELS[key]?.label ?? RULE_LABELS[key] ?? fallback;
}

export function fieldUnit(key) {
  return FIELD_LABELS[key]?.unit ?? '';
}

export function fieldDescription(key) {
  return FIELD_LABELS[key]?.description ?? '';
}

export function strategyLabel(key) {
  return FIELD_LABELS[key]?.label ?? STRATEGY_LABELS[key] ?? key;
}

export function operatorLabel(operator) {
  return OPERATOR_LABELS[operator] ?? operator;
}
