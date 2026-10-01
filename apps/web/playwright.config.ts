import {defineConfig} from '@playwright/test';

import {basePath} from './scripts/base_path.mjs';

// The tests run against the built static export (`pnpm build` first), served
// the way a static host serves it, so a link that escapes the base path
// fails here rather than after a deploy.
const PORT = 3100;
const SITE_URL = `http://127.0.0.1:${PORT}${basePath}/`;

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  // Two workers, as on a CI runner, so local and CI timings compare.
  workers: 2,
  forbidOnly: true,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: SITE_URL,
    browserName: 'chromium',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'node scripts/serve.mjs',
    env: {PORT: String(PORT)},
    url: SITE_URL,
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
