import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { PocApp } from './PocApp'
import '../styles/tailwind.css'
import '../styles/tokens.css'
import '../styles.css'
import '../styles/shell.css'
import '../styles/primitives.css'
import '../styles/chat.css'
import './poc.css'

const root = document.getElementById('root')
if (!root) throw new Error('POC root element is missing.')

createRoot(root).render(
  <StrictMode>
    <PocApp />
  </StrictMode>,
)
