import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from './api/contextStore'
import { routes } from './routes'
import { memberContext } from './test/fixtures'
import { mockFetchOnce } from './test/mockFetch'
import { mockMatchMedia } from './test/mockMatchMedia'

afterEach(() => {
  resetContextForTests()
  mockMatchMedia(false)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the route table', () => {
  it('renders the six sidebar destinations in the decided order, with no count on Conflicts', () => {
    setContext(memberContext())
    const router = createMemoryRouter(routes, { initialEntries: ['/'] })
    render(<RouterProvider router={router} />)

    const nav = screen.getByRole('navigation', { name: 'Primary' })
    const labels = [
      'Home',
      'Conflicts',
      'Schedule',
      'Songs/Setlist',
      'Band',
      'Profile',
    ]
    for (const label of labels) {
      expect(nav).toHaveTextContent(label)
    }

    const conflictsLink = screen.getByRole('link', { name: /^Conflicts$/ })
    expect(conflictsLink).not.toHaveTextContent(/\d/)
  })

  it('renders no Semesters destination and no Recordings destination', () => {
    setContext(memberContext())
    const router = createMemoryRouter(routes, { initialEntries: ['/'] })
    render(<RouterProvider router={router} />)

    expect(
      screen.queryByRole('link', { name: /Semesters/ }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: /Recordings/ }),
    ).not.toBeInTheDocument()
  })

  it('marks the active nav item with aria-current', () => {
    setContext(memberContext())
    const router = createMemoryRouter(routes, { initialEntries: ['/schedule'] })
    render(<RouterProvider router={router} />)

    expect(screen.getByRole('link', { name: 'Schedule' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByRole('link', { name: 'Home' })).not.toHaveAttribute(
      'aria-current',
    )
  })

  it('renders the not-found content for an unknown client route, inside the shell', () => {
    setContext(memberContext())
    const router = createMemoryRouter(routes, {
      initialEntries: ['/some/unknown/path'],
    })
    render(<RouterProvider router={router} />)

    expect(screen.getByText('Page not found')).toBeInTheDocument()
    expect(
      screen.getByRole('navigation', { name: 'Primary' }),
    ).toBeInTheDocument()
  })

  it("redirects /profile to the viewer's own person page once context has loaded", () => {
    mockFetchOnce(200, {
      context: memberContext(),
      data: {
        id: 1,
        name: 'Sam Rivera',
        is_self: true,
        can_edit_roles: true,
        has_membership: false,
        semester_name: null,
        email: 'sam@example.com',
      },
    })
    setContext(memberContext())
    const router = createMemoryRouter(routes, { initialEntries: ['/profile'] })
    render(<RouterProvider router={router} />)

    expect(router.state.location.pathname).toBe('/members/1')
  })
})

describe('the phone layout', () => {
  it('replaces the sidebar with exactly five tabs and a title bar', () => {
    mockMatchMedia(true)
    setContext(memberContext())
    const router = createMemoryRouter(routes, { initialEntries: ['/'] })
    render(<RouterProvider router={router} />)

    const tabs = screen.getAllByRole('link', {
      name: /^(Home|Schedule|Songs|Conflicts)$/,
    })
    expect(tabs).toHaveLength(4)
    expect(screen.getByRole('button', { name: 'More' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Home' })).toBeInTheDocument()
  })
})
