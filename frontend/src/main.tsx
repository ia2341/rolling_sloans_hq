import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './index.css'

const rootElement = document.getElementById('root')
if (rootElement === null) {
  throw new Error('Missing #root element in the SPA shell document.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
