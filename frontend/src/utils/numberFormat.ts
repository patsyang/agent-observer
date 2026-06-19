export function formatNumber(value: number): string {
  return new Intl.NumberFormat('zh-CN').format(value);
}

export function formatCount(value: number, unit: string): string {
  return `${formatNumber(value)} ${unit}`;
}
