import { useState } from 'react';

import type { HandleSignalPayload } from '../api/types';

interface Props {
  onCancel: () => void;
  onSubmit: (payload: HandleSignalPayload) => Promise<void>;
}

export function HandleSignalDialog({ onCancel, onSubmit }: Props) {
  const [conclusionCode, setConclusionCode] = useState<HandleSignalPayload['conclusion_code']>('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  return (
    <div className="modal-backdrop" role="presentation">
      <form
        className="modal"
        onSubmit={async (event) => {
          event.preventDefault();
          setSubmitting(true);
          await onSubmit({ conclusion_code: conclusionCode, note });
        }}
      >
        <h3>处理信号</h3>
        <label>
          结论
          <select value={conclusionCode} onChange={(event) => setConclusionCode(event.target.value as HandleSignalPayload['conclusion_code'])}>
            <option value="">请选择</option>
            <option value="known_issue">已知问题</option>
            <option value="needs_fix">需要修复</option>
            <option value="accepted_risk">接受风险</option>
            <option value="expected_nonzero_exit">期望非零退出</option>
            <option value="duplicate_signal">重复信号</option>
            <option value="not_actionable">无需处理</option>
          </select>
        </label>
        <label>
          备注
          <textarea value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <div className="modal-actions">
          <button type="button" onClick={onCancel}>取消</button>
          <button className="primary" disabled={!conclusionCode || submitting} type="submit">保存</button>
        </div>
      </form>
    </div>
  );
}
