import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PocApp } from './PocApp'
import '../styles/tailwind.css'
import '../styles/tokens.css'
import '../styles.css'
import '../styles/shell.css'
import '../styles/primitives.css'
import '../styles/chat.css'
import './poc.css'

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
if (!root) throw new Error('POC root element is missing.')

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <PocApp />
    </QueryClientProvider>
  </StrictMode>,
)
