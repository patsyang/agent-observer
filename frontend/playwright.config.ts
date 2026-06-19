import { defineConfig, devices } from '@playwright/test';

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
      env: { AGENT_OBSERVER_DB: '../data/e2e-agent-observer.sqlite' },
      url: 'http://127.0.0.1:8765/api/collectors',
      reuseExistingServer: false
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 4173',
      env: { VITE_API_BASE_URL: 'http://127.0.0.1:8765' },
      url: 'http://127.0.0.1:4173',
      reuseExistingServer: false
    }
  ]
});
