export const STORAGE_KEY = 'choose-stock-strategies-v1';
export const clone = value => JSON.parse(JSON.stringify(value));
export function withCoverageMetadata(config, defaults) {
  config.universe.downloaded_min_price = defaults.universe.downloaded_min_price;
  config.universe.downloaded_exclude_financials = defaults.universe.downloaded_exclude_financials;
  for (const category of ['quality', 'growth', 'momentum']) {
    const defaultById = new Map(defaults.qgm[category].map(rule => [rule.id, rule]));
    for (const rule of config.qgm[category]) {
      if (rule.enabled === undefined) rule.enabled = defaultById.get(rule.id)?.enabled ?? true;
    }
  }
  return config;
}
export function validateConfig(config) {
  if (!config || config.schema_version !== 1 || !config.universe || !config.qgm || !config.filters) throw new Error('設定檔格式不正確');
  for (const letter of 'abcde') if (!config[`strategy_${letter}`]?.conditions) throw new Error(`缺少策略 ${letter.toUpperCase()}`);
  const weights = ['quality', 'growth', 'momentum'].map(name => Number(config.qgm[`${name}_weight`]));
  if (weights.some(value => !Number.isFinite(value) || value < 0)) throw new Error('QGM 權重必須是非負數');
  if (Math.abs(weights.reduce((a,b) => a+b, 0) - 100) > 1e-8) throw new Error('QGM 權重總和必須等於 100');
  return config;
}
export function loadSettings(defaults, storage = localStorage) {
  try { return withCoverageMetadata(validateConfig(JSON.parse(storage.getItem(STORAGE_KEY))), defaults) }
  catch { return clone(defaults) }
}
export function saveSettings(config, storage = localStorage) {
  validateConfig(config);
  storage.setItem(STORAGE_KEY, JSON.stringify(config));
}
export function restoreDefault(defaults, storage = localStorage) {
  storage.removeItem(STORAGE_KEY);
  return clone(defaults);
}
export function exportText(config) { return JSON.stringify(validateConfig(config), null, 2) + '\n' }
export function parseImport(text, defaults = null) {
  const imported = JSON.parse(text);
  return validateConfig(defaults ? withCoverageMetadata(imported, defaults) : imported);
}
