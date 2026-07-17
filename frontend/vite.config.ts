import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  // Vite is started from frontend/, so its parent is the repository root where
  // the single deployment .env is rendered.
  const repositoryRoot = '..'
  const env = loadEnv(mode, repositoryRoot, '')
  const publicOrigin = env.APP_PUBLIC_ORIGIN || ''
  return {
    envDir: repositoryRoot,
    plugins: [react()],
    // Backend bootstrap owns these public OIDC values. Vite exposes only the
    // browser-safe subset instead of requiring a second, drifting .env file.
    define: {
      'import.meta.env.VITE_OIDC_AUTHORITY': JSON.stringify(env.OIDC_PUBLIC_AUTHORITY || ''),
      'import.meta.env.VITE_OIDC_CLIENT_ID': JSON.stringify(env.OIDC_CLIENT_ID || ''),
      'import.meta.env.VITE_OIDC_REDIRECT_URI': JSON.stringify(publicOrigin),
      'import.meta.env.VITE_OIDC_HIGH_ASSURANCE_ACR': JSON.stringify(env.OIDC_STEP_UP_ACR || '2'),
      'import.meta.env.VITE_OIDC_PASSWORD_REAUTH_ACR': JSON.stringify(env.OIDC_PASSWORD_REAUTH_ACR || '1'),
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      watch: env.VITE_USE_POLLING === 'true'
        ? { usePolling: true, interval: 250 }
        : undefined,
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: false,
        },
      },
    },
  }
})
