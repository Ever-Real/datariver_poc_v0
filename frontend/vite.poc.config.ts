import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The POC deliberately has its own entry graph. It neither loads deployment
// runtime configuration nor defines any OIDC/API build value.
export default defineConfig({
  base: './',
  publicDir: false,
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 39080,
    strictPort: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 39080,
    strictPort: true,
  },
  build: {
    outDir: 'dist-poc',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: 'poc.html',
    },
  },
})
