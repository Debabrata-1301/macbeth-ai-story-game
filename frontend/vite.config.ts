import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  // The shell value is authoritative for isolated Playwright runs. Keep dotenv for
  // normal local development, while ensuring a launched test backend is actually used.
  const backend = process.env.VITE_API_PROXY_TARGET || env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: backend,
          changeOrigin: true,
        },
      },
    },
  };
});
