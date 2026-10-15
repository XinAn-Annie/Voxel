import { defineConfig } from 'vite';

export default defineConfig({
  server: { proxy: { '/api': 'http://127.0.0.1:8003', '/samples': 'http://127.0.0.1:8003' } }
});
