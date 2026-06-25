import { useEffect } from 'react';

import type { ProcessingStatus } from '../api/types';

export function useProcessingStatusPolling(
  state: ProcessingStatus['state'],
  loadProcessingStatus: () => Promise<ProcessingStatus>,
  onStatus: (status: ProcessingStatus) => void
) {
  useEffect(() => {
    if (state !== 'pending' && state !== 'running') return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      loadProcessingStatus().then((status) => {
        if (!cancelled) onStatus(status);
      }).catch(() => undefined);
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [loadProcessingStatus, onStatus, state]);
}
