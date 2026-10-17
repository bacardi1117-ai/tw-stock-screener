// The same declarative strategies.json rules are interpreted by Python and the browser.
export const strategyKeys = ['strategy_a', 'strategy_b', 'strategy_c', 'strategy_d', 'strategy_e'];
export function number(value) {
  if (value === null || value === undefined || value === '' || typeof value === 'boolean') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function compare(left, op, right) {
  if (op === 'gt') return left > right;
  if (op === 'gte') return left >= right;
  if (op === 'lt') return left < right;
  if (op === 'lte') return left <= right;
  if (op === 'eq') return left === right;
  throw new Error(`Unknown operator: ${op}`);
}
const round4 = value => Math.round(value * 10000) / 10000;
export function qgmScores(row, config) {
  const qgm = config.qgm;
  const categories = ['quality', 'growth', 'momentum'];
  const weights = categories.map(name => number(qgm[`${name}_weight`]));
  if (weights.some(value => value === null || value < 0) || Math.abs(weights.reduce((a,b) => a+b, 0) - 100) > 1e-8) {
    throw new Error('QGM weights must total 100');
  }
  const result = {};
  categories.forEach((category, index) => {
    let earned = 0, maximum = 0;
    for (const rule of qgm[category]) {
      maximum += rule.kind === 'tiers' ? Math.max(0, ...rule.tiers.map(tier => tier.points)) : rule.points;
      let points = 0;
      if (rule.kind === 'tiers') {
        const value = number(row[rule.field]);
        const op = rule.direction === 'min' ? 'gte' : 'lte';
        if (value !== null) points = rule.tiers.find(tier => compare(value, op, tier.value))?.points ?? 0;
      } else if (rule.kind === 'compare') {
        const value = number(row[rule.field]);
        if (value !== null && compare(value, rule.op, rule.value)) points = rule.points;
      } else if (rule.kind === 'fields') {
        const left = number(row[rule.left]), right = number(row[rule.right]);
        if (left !== null && right !== null && compare(left, rule.op, right)) points = rule.points;
      } else throw new Error(`Unknown QGM rule: ${rule.kind}`);
      result[`${category}_${rule.id}`] = points;
      earned += points;
    }
    result[`score_${category}`] = maximum ? round4(earned / maximum * weights[index]) : 0;
  });
  result.score_total = round4(categories.reduce((sum, name) => sum + result[`score_${name}`], 0));
  return result;
}
export function evaluateStrategy(row, strategy) {
  if (!strategy.enabled) return 'unavailable';
  if ((strategy.availability_fields ?? []).some(field => number(row[field]) === null)) return 'unavailable';
  let missing = false, failed = false;
  for (const condition of Object.values(strategy.conditions)) {
    if (!condition.enabled) continue;
    const left = number(row[condition.field]);
    const right = number('right' in condition ? row[condition.right] : condition.value);
    if (left === null || right === null) missing = true;
    else if (!compare(left, condition.op, right)) failed = true;
  }
  return missing ? 'missing_data' : failed ? 'fail' : 'pass';
}
export function evaluateAll(row, config) {
  const result = {};
  for (const key of strategyKeys) {
    const status = evaluateStrategy(row, config[key]);
    result[key] = status;
    result[`${key}_missing_data`] = status === 'missing_data';
  }
  return result;
}
export function evaluateRows(rows, config) {
  return rows.map(row => ({...row, ...qgmScores(row, config), ...evaluateAll(row, config)}));
}
export function filterRows(rows, config, options = {}) {
  const u = config.universe, f = config.filters;
  const query = (options.query ?? '').trim().toLowerCase();
  const selected = options.strategies ?? [];
  return rows.filter(row => {
    const close = number(row.close);
    if (close === null || close < number(u.min_price)) return false;
    if (u.exclude_financials && row.is_financial === true) return false;
    if (query && !`${row.stock_id} ${row.stock_name}`.toLowerCase().includes(query)) return false;
    for (const [field, minimum] of Object.entries({
      score_total: f.score_total_min, score_quality: f.score_quality_min,
      score_growth: f.score_growth_min, score_momentum: f.score_momentum_min,
      data_completeness: f.data_completeness_min,
    })) {
      const value = number(row[field]);
      if (value === null || value < number(minimum)) return false;
    }
    return selected.length === 0 || selected.some(key => row[key] === 'pass');
  });
}
export function sortRows(rows, field, direction = 'desc') {
  const sign = direction === 'asc' ? 1 : -1;
  return [...rows].sort((a,b) => {
    const left = number(a[field]), right = number(b[field]);
    if (left === null && right === null) return String(a.stock_id).localeCompare(String(b.stock_id));
    if (left === null) return 1;
    if (right === null) return -1;
    return sign * (left - right) || String(a.stock_id).localeCompare(String(b.stock_id));
  });
}
