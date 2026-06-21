import { useState } from 'react';

import type { HandleStoryPayload } from '../api/types';

interface Props {
  onCancel: () => void;
  onSubmit: (payload: HandleStoryPayload) => Promise<void>;
}

const options = [
  { value: 'known_issue', label: '已知问题' },
  { value: 'needs_fix', label: '需要修复' },
  { value: 'accepted_risk', label: '接受风险' },
  { value: 'not_actionable', label: '无需处理' }
] as const;

export function HandleStoryDialog({ onCancel, onSubmit }: Props) {
  const [conclusionCode, setConclusionCode] = useState<HandleStoryPayload['conclusion_code']>('');
  const [note, setNote] = useState('');
  const [status, setStatus] = useState<'idle' | 'submitting' | 'success' | 'validation_error' | 'server_error'>('idle');

  async function submit() {
    if (!conclusionCode) {
      setStatus('validation_error');
      return;
    }
    setStatus('submitting');
    try {
      await onSubmit({ conclusion_code: conclusionCode, note });
      setStatus('success');
    } catch {
      setStatus('server_error');
    }
  }

  return (
    <section className="dialog" role="dialog" aria-label="处理信号">
      <h3>处理信号</h3>
      <label>
        结论
        <select value={conclusionCode} onChange={(event) => setConclusionCode(event.target.value as HandleStoryPayload['conclusion_code'])}>
          <option value="">选择结论</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        备注
        <textarea value={note} maxLength={240} onChange={(event) => setNote(event.target.value)} />
      </label>
      {status === 'validation_error' && <p role="alert">处理前必须选择结构化结论。</p>}
      {status === 'server_error' && <p role="alert">处理失败。请检查备注后重试。</p>}
      {status === 'success' && <p>信号已处理。</p>}
      <div className="dialog-actions">
        <button onClick={onCancel}>取消</button>
        <button className="primary" disabled={status === 'submitting'} onClick={submit}>
          {status === 'submitting' ? '正在处理...' : '处理'}
        </button>
      </div>
    </section>
  );
}
