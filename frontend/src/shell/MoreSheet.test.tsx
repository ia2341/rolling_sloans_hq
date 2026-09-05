import { screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { adminContext, memberContext } from '../test/fixtures'
import { renderShell } from '../test/renderShell'
import { MoreSheet } from './MoreSheet'

afterEach(() => {
  resetContextForTests()
})

describe('MoreSheet', () => {
  it('holds only Profile and Log out for a member', () => {
    setContext(memberContext())
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
    expect(screen.queryByText('Switch semester')).not.toBeInTheDocument()
    expect(screen.queryByText('New semester')).not.toBeInTheDocument()
    expect(screen.queryByText('Manage semesters')).not.toBeInTheDocument()
  })

  it('holds the three semester items plus Profile and Log out for an admin', () => {
    setContext(adminContext())
    renderShell(<MoreSheet open onOpenChange={() => {}} />)

    expect(screen.getByText('Switch semester')).toBeInTheDocument()
    expect(screen.getByText('New semester')).toBeInTheDocument()
    expect(screen.getByText('Manage semesters')).toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('Log out')).toBeInTheDocument()
  })
})
