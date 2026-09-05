import { RouterProvider } from 'react-router-dom'

import { router } from './router'

/** The application root, mounted once by `main.tsx`. */
export function App() {
  return <RouterProvider router={router} />
}
