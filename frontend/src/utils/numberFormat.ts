export function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

export function formatCount(value: number, unit: string): string {
  return `${formatNumber(value)} ${unit}`;
}

/** R2-E7: 将毫秒时长人性化显示（ms / s / m s / h m）。
 * M5: 修复边界 bug——原实现 Math.round(seconds % 60) 在 119500ms 等情况下
 * 产生 "1m 60s" 等非法显示。改用 tenths 预判进位。
 */
export function formatDuration(ms: number): string {
  if (ms <= 0) return '0ms';
  const roundedMs = Math.round(ms);
  if (roundedMs < 1000) return `${roundedMs}ms`;
  // M5: tenths 已对第二位四舍五入，>= 60 则进位到分钟
  const tenths = Math.round(ms / 100) / 10;
  if (tenths < 60) return `${tenths.toFixed(1)}s`;
  const totalSeconds = Math.round(tenths);
  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;  // 一定 < 60
  if (minutes < 60) return `${minutes}m${remainingSeconds > 0 ? ` ${remainingSeconds}s` : ''}`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;  // 一定 < 60
  return `${hours}h${remainingMinutes > 0 ? ` ${remainingMinutes}m` : ''}`;
}
