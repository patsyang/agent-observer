import { expect, type APIRequestContext } from '@playwright/test';

import { E2E_API_BASE } from './urls';

export async function enableEnrichment(request: APIRequestContext) {
  const policyResponse = await request.get(`${E2E_API_BASE}/api/policy`);
  expect(policyResponse.ok()).toBeTruthy();
  const policy = await policyResponse.json();
  if (policy.enrichment_mode === 'enabled') return policy;
  const updated = await request.patch(`${E2E_API_BASE}/api/policy`, {
    data: { expected_version: policy.policy_version, enrichment_mode: 'enabled' }
  });
  expect(updated.ok()).toBeTruthy();
  return updated.json();
}

export async function runProcessingJobs(request: APIRequestContext, maxRuns = 20) {
  for (let index = 0; index < maxRuns; index += 1) {
    const response = await request.post(`${E2E_API_BASE}/api/processing/jobs/run-once`);
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    if (body.status === 'idle') return;
  }
  throw new Error('processing jobs did not drain');
}
