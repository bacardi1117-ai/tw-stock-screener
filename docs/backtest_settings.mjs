// Resolve display defaults without changing the simulator's configuration rules.
export function resolveBacktestSettings(saved, manifest, defaults) {
  const config = {...defaults, ...(saved && typeof saved === 'object' ? saved : {})};
  const start = manifest.backtest_start && manifest.backtest_start > manifest.recent_year_start ?
    manifest.backtest_start : manifest.recent_year_start ?? manifest.start;
  const legacy = manifest.legacy_default_period;
  const usesLegacyDefault = saved?._dateDefaultsVersion !== 2 && legacy &&
    config.startDate === legacy.start && config.endDate === legacy.end;
  if (!config.startDate || !config.endDate || usesLegacyDefault) {
    config.startDate = start;
    config.endDate = manifest.end;
  }
  config._dateDefaultsVersion = 2;
  return config;
}
