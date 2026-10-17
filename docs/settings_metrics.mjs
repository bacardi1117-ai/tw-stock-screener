export const QGM_CATEGORIES = ['quality', 'growth', 'momentum'];

export function qgmMaximumPoints(qgm) {
  return Object.fromEntries(QGM_CATEGORIES.map(category => [category,
    qgm[category].reduce((sum, rule) => {
      if (rule.enabled === false) return sum;
      const maximum = rule.kind === 'tiers'
        ? Math.max(0, ...rule.tiers.map(tier => Number(tier.points) || 0))
        : Number(rule.points) || 0;
      return sum + maximum;
    }, 0),
  ]));
}

export function weightsMatchMaximum(qgm) {
  const maximum = qgmMaximumPoints(qgm);
  return Object.fromEntries(QGM_CATEGORIES.map(category => [category,
    Math.abs(maximum[category] - Number(qgm[`${category}_weight`])) <= 1e-8,
  ]));
}
