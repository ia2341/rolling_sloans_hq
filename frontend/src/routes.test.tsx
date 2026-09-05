import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { routes } from './routes'

/**
 * Proves the Vitest + React Testing Library harness runs in CI (issue #325)
 * — not behaviour that doesn't exist yet, which is issue #328's route table.
 */
describe('the route table', () => {
  it('renders the placeholder root route content at "/"', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/'] })
    render(<RouterProvider router={router} />)

    expect(screen.getByText('Rolling Sloans')).toBeInTheDocument()
  })

  it('renders the not-found content for an unknown client route', () => {
    const router = createMemoryRouter(routes, {
      initialEntries: ['/some/unknown/path'],
    })
    render(<RouterProvider router={router} />)

    expect(screen.getByText('Page not found')).toBeInTheDocument()
  })
})
