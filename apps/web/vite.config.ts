import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ mode }) => ({
  define: mode === 'test' ? {} : { 'import.meta.env.VITE_DEMO_MODE': JSON.stringify(mode === 'demo' ? 'true' : 'false') },
  plugins: [react()],
  build: mode === 'demo' ? {
    rolldownOptions: { input: { main: 'index.html', preview: 'demo-preview.html' } },
  } : {},
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    clearMocks: true,
    restoreMocks: true,
  },
}));
