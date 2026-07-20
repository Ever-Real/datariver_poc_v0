import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { AuthProvider } from './auth/AuthProvider'
import './styles/tailwind.css'
import './styles/tokens.css'
import './styles.css'
import './styles/shell.css'
import './styles/primitives.css'

const root = document.getElementById('root')
if (!root) throw new Error('Root element is missing.')

createRoot(root).render(
  <StrictMode>
    <AuthProvider><App /></AuthProvider>
  </StrictMode>,
)
