import type { TimeWindow } from '../api/types';
import { quickTimeOptions } from './timeRangeOptions';

export function TimeWindowTabs({
  value,
  onChange,
}: {
  value: TimeWindow;
  onChange: (value: TimeWindow) => void;
}) {
  return (
    <div className="segmented-control" aria-label="时间范围" role="group">
      {quickTimeOptions.map((option) => (
        <button
          className={value === option.value ? 'active' : ''}
          key={option.value}
          onClick={() => onChange(option.value)}
          type="button"
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
