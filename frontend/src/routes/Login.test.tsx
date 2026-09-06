import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../test/fixtures'
import { mockFetchByUrl } from '../test/mockFetch'
import { Login } from './Login'

/** Renders `Login` (deliberately outside `AppShell`/`ContextProvider` — see its own docstring) behind `/login`, with a stub `/` to detect a post-sign-in redirect. */
function renderLogin(initialEntry = '/login') {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>Home stub</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Login', () => {
  it('renders Email, Password and a Sign In button once the status check reports unauthenticated', async () => {
    mockFetchByUrl({
      '/api/login/': () => ({ status: 200, body: { authenticated: false } }),
    })

    renderLogin()

    expect(
      await screen.findByRole('button', { name: 'Sign In' }),
    ).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
  })

  it('renders no forgot-password or sign-up link', async () => {
    mockFetchByUrl({
      '/api/login/': () => ({ status: 200, body: { authenticated: false } }),
    })

    renderLogin()

    await screen.findByRole('button', { name: 'Sign In' })
    expect(screen.queryByText(/forgot/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/sign up/i)).not.toBeInTheDocument()
  })

  it('redirects an already-authenticated visitor to Home without showing the form', async () => {
    mockFetchByUrl({
      '/api/login/': () => ({
        status: 200,
        body: { authenticated: true, context: memberContext() },
      }),
    })

    renderLogin()

    await screen.findByText('Home stub')
    expect(
      screen.queryByRole('button', { name: 'Sign In' }),
    ).not.toBeInTheDocument()
  })

  it('submits credentials and redirects to Home on success', async () => {
    const user = userEvent.setup()
    let postedBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          const url = typeof input === 'string' ? input : input.toString()
          if (!url.includes('/api/login/')) {
            throw new Error(`No mock handler registered for fetch(${url})`)
          }
          if ((init?.method ?? 'GET').toUpperCase() === 'GET') {
            return Promise.resolve({
              status: 200,
              ok: true,
              json: () => Promise.resolve({ authenticated: false }),
            })
          }
          postedBody = JSON.parse(init?.body as string)
          return Promise.resolve({
            status: 200,
            ok: true,
            json: () => Promise.resolve({ ok: true, context: memberContext() }),
          })
        }),
    )

    renderLogin()

    await user.type(await screen.findByLabelText('Email'), 'sam@example.com')
    await user.type(screen.getByLabelText('Password'), 'a-strong-password')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))

    await screen.findByText('Home stub')
    expect(postedBody).toEqual({
      email: 'sam@example.com',
      password: 'a-strong-password',
    })
  })

  it('shows a generic error message for invalid credentials, without redirecting', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          const url = typeof input === 'string' ? input : input.toString()
          if (!url.includes('/api/login/')) {
            throw new Error(`No mock handler registered for fetch(${url})`)
          }
          if ((init?.method ?? 'GET').toUpperCase() === 'GET') {
            return Promise.resolve({
              status: 200,
              ok: true,
              json: () => Promise.resolve({ authenticated: false }),
            })
          }
          return Promise.resolve({
            status: 200,
            ok: true,
            json: () =>
              Promise.resolve({ ok: false, reason: 'invalid_credentials' }),
          })
        }),
    )

    renderLogin()

    await user.type(await screen.findByLabelText('Email'), 'sam@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))

    expect(
      await screen.findByText('Incorrect email or password.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Home stub')).not.toBeInTheDocument()
  })

  it('shows a throttled message when the rate limit trips', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          const url = typeof input === 'string' ? input : input.toString()
          if (!url.includes('/api/login/')) {
            throw new Error(`No mock handler registered for fetch(${url})`)
          }
          if ((init?.method ?? 'GET').toUpperCase() === 'GET') {
            return Promise.resolve({
              status: 200,
              ok: true,
              json: () => Promise.resolve({ authenticated: false }),
            })
          }
          return Promise.resolve({
            status: 200,
            ok: true,
            json: () => Promise.resolve({ ok: false, reason: 'throttled' }),
          })
        }),
    )

    renderLogin()

    await user.type(await screen.findByLabelText('Email'), 'sam@example.com')
    await user.type(screen.getByLabelText('Password'), 'whatever')
    await user.click(screen.getByRole('button', { name: 'Sign In' }))

    await waitFor(() =>
      expect(screen.getByText(/too many attempts/i)).toBeInTheDocument(),
    )
  })
})
