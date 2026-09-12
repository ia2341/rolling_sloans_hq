import { screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { memberContext } from '../test/fixtures'
import { mockFetchByUrl } from '../test/mockFetch'
import { renderShell } from '../test/renderShell'
import { ThemeToggle } from './ThemeToggle'

describe('ThemeToggle', () => {
  afterEach(() => {
    resetContextForTests()
  })

  it('marks the current preference pressed and posts a change on click', async () => {
    setContext(memberContext())
    mockFetchByUrl({
      '/api/theme/': () => ({
        status: 200,
        body: {
          context: memberContext({
            viewer: { ...memberContext().viewer, theme_preference: 'dark' },
          }),
          ok: true,
          errors: {},
          non_field_errors: [],
          fallout: null,
          values: null,
          data: null,
        },
      }),
    })

    const user = (await import('@testing-library/user-event')).default.setup()
    renderShell(<ThemeToggle />)

    expect(
      screen.getByRole('button', { name: 'Match system theme' }),
    ).toHaveAttribute('aria-pressed', 'true')

    await user.click(screen.getByRole('button', { name: 'Dark theme' }))

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Dark theme' }),
      ).toHaveAttribute('aria-pressed', 'true'),
    )
    expect(
      screen.getByRole('button', { name: 'Match system theme' }),
    ).toHaveAttribute('aria-pressed', 'false')
  })
})
