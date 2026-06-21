import { useEffect, useState } from 'react';

import type { ConversationTimeWindow } from '../api/types';

type RangeValue = {
  window: ConversationTimeWindow | '';
  start_at: string;
  end_at: string;
};

type TimeOption = {
  value: ConversationTimeWindow;
  label: string;
};

export function TimeRangePicker({
  end,
  onApply,
  options,
  start,
  window,
}: {
  end: string;
  onApply: (value: RangeValue) => void;
  options: TimeOption[];
  start: string;
  window: ConversationTimeWindow | '';
}) {
  const [open, setOpen] = useState(false);
  const [draftEnd, setDraftEnd] = useState(toLocalInput(end));
  const [draftStart, setDraftStart] = useState(toLocalInput(start));

  useEffect(() => {
    setDraftStart(toLocalInput(start));
    setDraftEnd(toLocalInput(end));
  }, [start, end]);

  const selectedQuickLabel = options.find((option) => option.value === window)?.label ?? '1小时';
  const label = start || end ? rangeLabel(start, end) : selectedQuickLabel;
  const title = rangeTitle(start, end);

  return (
    <div className="conversation-range-picker">
      <button
        aria-expanded={open}
        aria-label={`时间范围：${label}`}
        className="conversation-range-trigger"
        onClick={() => setOpen((current) => !current)}
        title={title}
        type="button"
      >
        {label}
      </button>
      {open && (
        <div className="conversation-range-panel">
          <div className="conversation-quick-range-list" aria-label="快捷时间范围">
            {options.map((option) => (
              <button
                className={option.value === window && !start && !end ? 'compact-button selected' : 'compact-button'}
                key={option.value}
                onClick={() => {
                  onApply({ window: option.value, start_at: '', end_at: '' });
                  setOpen(false);
                }}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          <label>
            开始
            <input aria-label="开始" type="datetime-local" step={1} value={draftStart} onChange={(event) => setDraftStart(event.target.value)} />
          </label>
          <label>
            结束
            <input aria-label="结束" type="datetime-local" step={1} value={draftEnd} onChange={(event) => setDraftEnd(event.target.value)} />
          </label>
          <div className="conversation-range-actions">
            <button className="compact-button" onClick={() => {
              onApply({ window: '', start_at: toIso(draftStart), end_at: toIso(draftEnd) });
              setOpen(false);
            }} type="button">确认</button>
          </div>
        </div>
      )}
    </div>
  );
}

function toIso(value: string): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toISOString();
}

function toLocalInput(value: string): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 19);
}

function rangeLabel(start: string, end: string): string {
  if (!start && !end) return '1小时';
  if (start && end) return `${formatCompact(start)} - ${formatCompact(end, start)}`;
  if (start) return `开始 ${formatCompact(start)}`;
  return `结束 ${formatCompact(end)}`;
}

function rangeTitle(start: string, end: string): string {
  if (!start && !end) return '快捷时间范围';
  return `自定义 ${rangeLabel(start, end)}`;
}

function formatCompact(value: string, reference?: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const sameDate = reference ? date.toDateString() === new Date(reference).toDateString() : false;
  const time = date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  if (sameDate) return time;
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${month}/${day} ${time}`;
}
