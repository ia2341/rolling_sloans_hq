import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

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
})
