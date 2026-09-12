import { act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { resetContextForTests, setContext } from '../api/contextStore'
import { memberContext } from '../test/fixtures'
import { renderShell } from '../test/renderShell'
import { ThemeSync } from './ThemeSync'

describe('ThemeSync', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  afterEach(() => {
    resetContextForTests()
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  it('applies no data-theme attribute before any context has arrived', () => {
    renderShell(<ThemeSync />)

    expect(document.documentElement.dataset.theme).toBeUndefined()
  })

  it('applies and caches an explicit dark preference from context', async () => {
    setContext(
      memberContext({
        viewer: { ...memberContext().viewer, theme_preference: 'dark' },
      }),
    )
    renderShell(<ThemeSync />)

    await Promise.resolve()

    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('rs-theme-preference')).toBe('dark')
  })

  it('clears data-theme when context updates to system', async () => {
    setContext(
      memberContext({
        viewer: { ...memberContext().viewer, theme_preference: 'dark' },
      }),
    )
    renderShell(<ThemeSync />)
    await Promise.resolve()

    act(() => {
      setContext(memberContext({ viewer: memberContext().viewer }))
    })

    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(localStorage.getItem('rs-theme-preference')).toBe('system')
  })
})
