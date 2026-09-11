import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { memberContext } from '../test/fixtures'
import { mockFetchByUrl } from '../test/mockFetch'
import { ChangePassword } from './ChangePassword'

/** Renders `ChangePassword` (deliberately outside `AppShell`, see its own docstring) behind `/change-password`, with a stub `/` to detect a post-save redirect. */
function renderChangePassword() {
  return render(
    <MemoryRouter initialEntries={['/change-password']}>
      <Routes>
        <Route path="/change-password" element={<ChangePassword />} />
        <Route path="/" element={<div>Home stub</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('ChangePassword', () => {
  it('renders the three password fields and a submit button', () => {
    renderChangePassword()

    expect(screen.getByLabelText('Temp password')).toBeInTheDocument()
    expect(screen.getByLabelText('New password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm new password')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Save password' }),
    ).toBeInTheDocument()
  })

  it('submits the three fields to /api/password/ and redirects Home on success', async () => {
    const user = userEvent.setup()
    let postedBody: unknown = null
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
          const url = typeof input === 'string' ? input : input.toString()
          if (!url.includes('/api/password/')) {
            throw new Error(`No mock handler registered for fetch(${url})`)
          }
          postedBody = JSON.parse(init?.body as string)
          return Promise.resolve({
            status: 200,
            ok: true,
            json: () => Promise.resolve({ ok: true, context: memberContext() }),
          })
        }),
    )

    renderChangePassword()

    await user.type(screen.getByLabelText('Temp password'), 'temp-pw-123')
    await user.type(
      screen.getByLabelText('New password'),
      'a-new-strong-password',
    )
    await user.type(
      screen.getByLabelText('Confirm new password'),
      'a-new-strong-password',
    )
    await user.click(screen.getByRole('button', { name: 'Save password' }))

    await screen.findByText('Home stub')
    expect(postedBody).toEqual({
      old_password: 'temp-pw-123',
      new_password1: 'a-new-strong-password',
      new_password2: 'a-new-strong-password',
    })
  })

  it('shows per-field errors and does not redirect on a rejected change', async () => {
    const user = userEvent.setup()
    mockFetchByUrl({
      '/api/password/': () => ({
        status: 200,
        body: {
          ok: false,
          errors: { old_password: ['That password is incorrect.'] },
          non_field_errors: [],
          context: memberContext(),
        },
      }),
    })

    renderChangePassword()

    await user.type(screen.getByLabelText('Temp password'), 'wrong')
    await user.type(
      screen.getByLabelText('New password'),
      'a-new-strong-password',
    )
    await user.type(
      screen.getByLabelText('Confirm new password'),
      'a-new-strong-password',
    )
    await user.click(screen.getByRole('button', { name: 'Save password' }))

    expect(
      await screen.findByText('That password is incorrect.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Home stub')).not.toBeInTheDocument()
  })
})
