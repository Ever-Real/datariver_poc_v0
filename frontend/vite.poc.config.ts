import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The POC deliberately has its own entry graph. It neither loads deployment
// runtime configuration nor defines any OIDC/API build value.
type ProcessLike = {
  cwd?: () => string
  env?: Record<string, string | undefined>
}

const processLike = (globalThis as { process?: ProcessLike }).process
const workingDirectory = processLike?.cwd?.() ?? '.'
const pocModule = (name: string) => `${workingDirectory}/src/poc/${name}`
export const pocDevelopmentHost = (environment: Record<string, string | undefined> = processLike?.env ?? {}) => (
  environment.POC_SERVER_HOST?.trim() || '127.0.0.1'
)
const developmentHost = pocDevelopmentHost()
const pocDevelopmentIndex = {
  name: 'datariver-poc-development-index',
  transformIndexHtml: {
    order: 'pre' as const,
    handler(html: string, context: { path: string }) {
      if (context.path !== '/' && context.path !== '/index.html') return html
      return html
        .replace(/\s*<script src="\/runtime-config\.js"><\/script>/, '')
        .replace('/src/main.tsx', '/src/poc/main.tsx')
        .replace('<title>DataRiver</title>', '<title>DataRiver Static POC</title>')
    },
  },
}

export default defineConfig({
  base: './',
  publicDir: false,
  plugins: [pocDevelopmentIndex, react(), tailwindcss()],
  resolve: {
    alias: [
      {
        find: /^(?:.*\/)?auth\/AuthProvider$/,
        replacement: pocModule('pocAuthCompat.ts'),
      },
      {
        find: /^(?:.*\/)?api\/useStableApiClient$/,
        replacement: pocModule('pocApi.ts'),
      },
      {
        find: /^(?:.*\/)?api\/client$/,
        replacement: pocModule('pocClientCompat.ts'),
      },
      {
        find: /^(?:.*\/)?runtimeConfig$/,
        replacement: pocModule('pocRuntimeConfig.ts'),
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
    outDir: 'dist-poc',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: {
      input: 'poc.html',
    },
  },
})
