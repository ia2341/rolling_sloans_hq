import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { RegisterTestEditSession } from '../test/RegisterTestEditSession'
import { adminContext, memberContext } from '../test/fixtures'
import { renderShell } from '../test/renderShell'
import { usePageTitle } from './PageTitleContext'
import { TopBar } from './TopBar'

afterEach(() => {
  resetContextForTests()
})

/** A minimal route stand-in that registers `title` via `usePageTitle()`, for asserting what `TopBar` renders. */
function TitledPage({ title }: { title: string }) {
  usePageTitle(title)
  return null
}

describe('TopBar', () => {
  it("names the current surface from the page's registered title", () => {
    setContext(memberContext())
    renderShell(
      <>
        <TitledPage title="Edit setlist" />
        <TopBar />
      </>,
    )

    expect(
      screen.getByRole('heading', { name: 'Edit setlist' }),
    ).toBeInTheDocument()
  })

  it('disables Save with no pending changes and hides Publish for a member', () => {
    setContext(memberContext())
    renderShell(<TopBar />)

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(
      screen.queryByRole('button', { name: 'Publish' }),
    ).not.toBeInTheDocument()
  })

  it('hides Discard with no editing surface registered', () => {
    setContext(memberContext())
    renderShell(<TopBar />)

    expect(
      screen.queryByRole('button', { name: 'Discard' }),
    ).not.toBeInTheDocument()
  })

  it('shows an enabled Discard once a surface registers an EditSession, and calls its discard (issue: UI overhaul round 2, item 6 — a phone viewer previously had no way to leave edit mode without saving)', async () => {
    setContext(adminContext())
    const discard = vi.fn()
    const user = userEvent.setup()
    renderShell(
      <>
        <RegisterTestEditSession changeCount={1} discard={discard} />
        <TopBar />
      </>,
    )

    await user.click(screen.getByRole('button', { name: 'Discard' }))

    expect(discard).toHaveBeenCalledTimes(1)
  })

  it('shows the block note above the bar and disables both actions while blocked', () => {
    setContext(adminContext())
    renderShell(
      <>
        <RegisterTestEditSession
          changeCount={2}
          blockedReason="Reload and reapply your edits."
        />
        <TopBar />
      </>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent(
      'Reload and reapply your edits.',
    )
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
  })

  it('enables Publish for an admin viewing an unpublished draft with nothing blocking', () => {
    setContext(adminContext())
    renderShell(<TopBar />)

    expect(screen.getByRole('button', { name: 'Publish' })).toBeEnabled()
  })

  it('shows the semester strip naming the viewing (non-live) Semester with a Switch button', () => {
    setContext(adminContext())
    renderShell(<TopBar />)

    expect(
      screen.getByText('Viewing Fall 2026 (draft) — not what members see'),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Switch' })).toBeInTheDocument()
  })

  it('hides the semester strip once the viewing Semester is live', () => {
    setContext(memberContext())
    renderShell(<TopBar />)

    expect(screen.queryByText(/not what members see/)).not.toBeInTheDocument()
  })
})
