import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { RegisterTestEditSession } from '../test/RegisterTestEditSession'
import { adminContext, memberContext } from '../test/fixtures'
import { renderShell } from '../test/renderShell'
import { Sidebar } from './Sidebar'

afterEach(() => {
  resetContextForTests()
  window.localStorage.clear()
})

describe('Sidebar', () => {
  it('collapsing hides nav labels and the semester panel body but keeps the block note glyph', async () => {
    setContext(adminContext())
    renderShell(
      <>
        <RegisterTestEditSession blockedReason="Someone else saved Fall 2026 (draft) while you were editing." />
        <Sidebar />
      </>,
    )

    expect(screen.getByText('Home')).toBeInTheDocument()
    expect(screen.getByText(/Viewing: Fall 2026/)).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Someone else saved')

    await userEvent.click(
      screen.getByRole('button', { name: 'Collapse sidebar' }),
    )

    expect(screen.queryByText('Home')).not.toBeInTheDocument()
    expect(screen.queryByText(/Viewing: Fall 2026/)).not.toBeInTheDocument()
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('renders the semester panel only for an admin', () => {
    setContext(memberContext())
    renderShell(<Sidebar />)

    expect(screen.queryByText(/Viewing:/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Publish' }),
    ).not.toBeInTheDocument()
  })

  it('shows the draft warning naming the Live Semester when viewing a non-live Semester', () => {
    setContext(adminContext())
    renderShell(<Sidebar />)

    expect(
      screen.getByText('Not what members see — they see Spring 2026'),
    ).toBeInTheDocument()
  })

  it('disables Save changes and Publish while blocked', () => {
    setContext(adminContext())
    renderShell(
      <>
        <RegisterTestEditSession
          changeCount={2}
          blockedReason="The setlist changed while you were editing."
        />
        <Sidebar />
      </>,
    )

    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  })

  it('enables Save changes once there are pending changes and nothing is blocking', () => {
    setContext(adminContext())
    renderShell(
      <>
        <RegisterTestEditSession changeCount={3} blockedReason={null} />
        <Sidebar />
      </>,
    )

    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
  })

  it('renders without error before any Semester has been published', () => {
    setContext(
      adminContext({
        viewing_semester: null,
        live_semester: null,
        semester_warning: false,
      }),
    )
    renderShell(<Sidebar />)

    expect(screen.getByText('No Semester published yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Publish' })).toBeDisabled()
  })
})
