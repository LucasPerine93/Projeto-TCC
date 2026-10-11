import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev server em 5173 — mesma origem liberada no CORS do backend.
export default defineConfig({
  plugins: [react()],
});
