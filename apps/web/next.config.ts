import type {NextConfig} from 'next';

import {basePath} from './scripts/base_path.mjs';

// A static export: every page is HTML written at build time from committed
// files, so the site needs no server and runs no request-time code.
const nextConfig: NextConfig = {
  output: 'export',
  basePath,
  trailingSlash: true,
  images: {unoptimized: true},
  reactStrictMode: true,
};

export default nextConfig;
