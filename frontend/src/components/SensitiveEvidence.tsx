import type { SensitiveMatch } from '../api/types';
import { sensitiveCategoryLabel } from './signalLabels';

interface Props {
  matches?: SensitiveMatch[];
}

export function SensitiveEvidence({ matches }: Props) {
  if (!matches || matches.length === 0) return null;
  const deduped = new Map<string, SensitiveMatch>();
  for (const m of matches) {
    const key = `${m.category}:${m.matched_value}`;
    if (!deduped.has(key)) deduped.set(key, m);
  }
  return (
    <div className="sensitive-evidence" data-testid="sensitive-evidence">
      <strong>命中敏感内容：</strong>
      {Array.from(deduped.values()).map((m) => (
        <span key={`${m.category}:${m.matched_value}`} className="sensitive-match-tag">
          {sensitiveCategoryLabel(m.category)}：{m.matched_value}
        </span>
      ))}
    </div>
  );
}
