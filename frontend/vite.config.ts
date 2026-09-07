import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // Vite is started from frontend/, so its parent is the repository root where
  // the single deployment .env is rendered.
  const repositoryRoot = '..'
  const env = loadEnv(mode, repositoryRoot, '')
  // `loadEnv` intentionally does not merge process values. Host development
  // injects VITE_* values for the selected ports, so prefer those explicit
  // process values before the repository deployment file.
  const processEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } })
    .process?.env ?? {}
  const value = (name: string) => processEnv[name] || env[name] || ''
  const publicOrigin = value('VITE_OIDC_REDIRECT_URI') || value('APP_PUBLIC_ORIGIN')
  const apiPort = value('API_PORT') || '38101'
  const webPort = Number(value('WEB_PORT') || '38102')
  const allowedHosts = value('VITE_ALLOWED_HOSTS')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean)
  return {
    envDir: repositoryRoot,
    plugins: [react(), tailwindcss()],
    // Backend bootstrap owns these public OIDC values. Vite exposes only the
    // browser-safe subset instead of requiring a second, drifting .env file.
    define: {
      'import.meta.env.VITE_OIDC_AUTHORITY': JSON.stringify(value('VITE_OIDC_AUTHORITY') || value('OIDC_PUBLIC_AUTHORITY')),
      'import.meta.env.VITE_OIDC_CLIENT_ID': JSON.stringify(value('VITE_OIDC_CLIENT_ID') || value('OIDC_CLIENT_ID')),
      'import.meta.env.VITE_OIDC_REDIRECT_URI': JSON.stringify(publicOrigin),
      'import.meta.env.VITE_OIDC_HIGH_ASSURANCE_ACR': JSON.stringify(value('VITE_OIDC_HIGH_ASSURANCE_ACR') || value('OIDC_STEP_UP_ACR') || '2'),
      'import.meta.env.VITE_OIDC_PASSWORD_REAUTH_ACR': JSON.stringify(value('VITE_OIDC_PASSWORD_REAUTH_ACR') || value('OIDC_PASSWORD_REAUTH_ACR') || '1'),
    },
    server: {
      host: '127.0.0.1',
      port: webPort,
      strictPort: true,
      allowedHosts: allowedHosts.length > 0 ? allowedHosts : undefined,
      watch: value('VITE_USE_POLLING') === 'true'
        ? { usePolling: true, interval: 250 }
        : undefined,
      proxy: {
        '/api': {
          target: value('VITE_API_PROXY_TARGET') || `http://localhost:${apiPort}`,
          changeOrigin: false,
        },
      },
    },
    build: {
      rollupOptions: {
        input: {
          main: 'index.html',
          'oidc-silent-callback': 'oidc-silent-callback.html',
        },
      },
    },
  }
})
