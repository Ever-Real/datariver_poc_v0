import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Application } from './Application'
import { SiteBrandingProvider } from '../components/layout/SiteBranding'
import { installPocRandomUuidCompatibility } from './uuidCompat'
import '../styles/tailwind.css'
import '../styles/tokens.css'
import '../styles.css'
import '../styles/shell.css'
import '../styles/primitives.css'
import '../styles/chat.css'
import './application.css'

// The local-session UI supports intranet HTTP under the server's origin policy. Web Crypto's
// randomUUID may be absent there, while getRandomValues remains available.
installPocRandomUuidCompatibility()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 10 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: false,
    },
  },
})

const root = document.getElementById('root')
if (!root) throw new Error('Application root element is missing.')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SiteBrandingProvider><Application /></SiteBrandingProvider>
    </QueryClientProvider>
  </StrictMode>,
)
