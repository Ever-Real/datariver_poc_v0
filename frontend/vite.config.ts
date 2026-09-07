import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The local-session UI has its own entry graph. It neither loads deployment
// runtime configuration nor defines any OIDC/API build value.
type ProcessLike = {
  cwd?: () => string
  env?: Record<string, string | undefined>
}

const processLike = (globalThis as { process?: ProcessLike }).process
const workingDirectory = decodeURIComponent(new URL('.', import.meta.url).pathname).replace(/\/$/, '')
const applicationModule = (name: string) => `${workingDirectory}/src/app/${name}`
export const developmentServerHost = (environment: Record<string, string | undefined> = processLike?.env ?? {}) => (
  environment.POC_SERVER_HOST?.trim() || '127.0.0.1'
)
const developmentHost = developmentServerHost()
const developmentIndex = {
  name: 'datariver-development-index',
  transformIndexHtml: {
    order: 'pre' as const,
    handler(html: string, context: { path: string }) {
      if (context.path !== '/' && context.path !== '/index.html') return html
      return html
        .replace(/\s*<script src="\/runtime-config\.js"><\/script>/, '')
        .replace('/src/main.tsx', '/src/app/main.tsx')
        .replace('<title>DataRiver</title>', '<title>DataRiver</title>')
    },
  },
}

export default defineConfig({
  root: workingDirectory,
  base: './',
  publicDir: false,
  plugins: [developmentIndex, react(), tailwindcss()],
  resolve: {
    alias: [
      {
        find: /^(?:.*\/)?auth\/AuthProvider$/,
        replacement: applicationModule('authCompat.ts'),
      },
      {
        find: /^(?:.*\/)?api\/useStableApiClient$/,
        replacement: applicationModule('api.ts'),
      },
      {
        find: /^(?:.*\/)?api\/client$/,
        replacement: applicationModule('clientCompat.ts'),
      },
      {
        find: /^(?:.*\/)?runtimeConfig$/,
        replacement: applicationModule('runtimeConfig.ts'),
      },
    ],
  },
  server: {
    host: developmentHost,
    port: 39080,
    strictPort: true,
  },
  preview: {
    host: developmentHost,
    port: 39080,
    strictPort: true,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: `${workingDirectory}/index.html`,
    },
  },
})
