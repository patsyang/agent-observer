import type { TimeWindow } from '../api/types';

export const quickTimeOptions: Array<{ value: TimeWindow; label: string }> = [
  { value: '1h', label: '1小时' },
  { value: '3h', label: '3小时' },
  { value: '6h', label: '6小时' },
  { value: '12h', label: '12小时' },
  { value: 'today', label: '今天' },
  { value: 'week', label: '本周' },
  { value: 'all', label: '全部' },
];
