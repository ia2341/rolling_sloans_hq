import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import './index.css'
import { applyThemePreference, readCachedThemePreference } from './theme/theme'

// Applied synchronously, before the first render: the cached preference
// from the viewer's last session (issue #497) avoids a flash of the wrong
// theme while waiting for the first `/api/` response to confirm it.
applyThemePreference(readCachedThemePreference())

const rootElement = document.getElementById('root')
if (rootElement === null) {
  throw new Error('Missing #root element in the SPA shell document.')
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
