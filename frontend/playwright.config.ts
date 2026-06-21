import { defineConfig, devices } from '@playwright/test';

const e2eApiBase = 'http://127.0.0.1:8766';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:4173',
    ...devices['Desktop Chrome']
  },
  webServer: [
    {
      command: 'python -c "from pathlib import Path; [p.unlink(missing_ok=True) for p in [Path(\'../data/e2e-agent-observer.sqlite\'), Path(\'../data/e2e-agent-observer.sqlite-wal\'), Path(\'../data/e2e-agent-observer.sqlite-shm\')]]" && python -m app.dev_server',
      cwd: '../backend',
      env: {
        AGENT_OBSERVER_DB: '../data/e2e-agent-observer.sqlite',
        AGENT_OBSERVER_PORT: '8766',
        AGENT_OBSERVER_PUBLIC_BASE_URL: e2eApiBase
      },
      url: `${e2eApiBase}/api/collectors`,
      reuseExistingServer: false
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      env: { VITE_API_BASE_URL: e2eApiBase },
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: false
    }
  ]
});
