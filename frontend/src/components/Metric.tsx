import type { ReactNode } from 'react';

interface Props {
  label: string;
  value: ReactNode;
  note: string;
}

export function Metric({ label, value, note }: Props) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{note}</small>
    </div>
  );
}
