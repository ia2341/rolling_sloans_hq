import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiFetch } from './client'
import { resetContextForTests } from './contextStore'

const originalLocation = window.location

/** Replaces `window.location` with a stub carrying a spy-able `assign()` -- jsdom's real `location.assign` can't be `vi.spyOn`'d directly. */
function stubLocationAssign(): ReturnType<typeof vi.fn> {
  const assign = vi.fn()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...originalLocation, assign },
  })
  return assign
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  resetContextForTests()
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: originalLocation,
  })
})

describe('apiFetch', () => {
  it('navigates to /login and never resolves on a 401', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 401,
        ok: false,
        json: () => Promise.resolve({ error: 'authentication_required' }),
      }),
    )
    const assignSpy = stubLocationAssign()

    let resolved = false
    void apiFetch('/api/schedule/').then(() => {
      resolved = true
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(assignSpy).toHaveBeenCalledWith('/login')
    expect(resolved).toBe(false)
  })

  it('navigates to /change-password and never resolves on a 403 password_change_required (issue #487)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 403,
        ok: false,
        json: () => Promise.resolve({ error: 'password_change_required' }),
      }),
    )
    const assignSpy = stubLocationAssign()

    let resolved = false
    void apiFetch('/api/schedule/').then(() => {
      resolved = true
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(assignSpy).toHaveBeenCalledWith('/change-password')
    expect(resolved).toBe(false)
  })

  it('rejects a plain 403 (e.g. admin_required) with ApiError, without redirecting', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        status: 403,
        ok: false,
        json: () => Promise.resolve({ error: 'admin_required' }),
      }),
    )
    const assignSpy = stubLocationAssign()

    await expect(apiFetch('/api/schedule/')).rejects.toMatchObject({
      status: 403,
    })
    expect(assignSpy).not.toHaveBeenCalled()
  })
})
