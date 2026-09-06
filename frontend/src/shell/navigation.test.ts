import { describe, expect, it } from 'vitest'

import { SIDEBAR_NAV_ITEMS, isNavItemActive } from './navigation'

const bandItem = SIDEBAR_NAV_ITEMS.find((item) => item.key === 'band')
const profileItem = SIDEBAR_NAV_ITEMS.find((item) => item.key === 'profile')

if (bandItem === undefined || profileItem === undefined) {
  throw new Error('expected Band and Profile nav items to exist')
}

describe('isNavItemActive', () => {
  it('highlights Profile, not Band, on your own /members/:personId (issue #363)', () => {
    const location = { pathname: '/members/2', search: '' }

    expect(isNavItemActive(profileItem, location, 2)).toBe(true)
    expect(isNavItemActive(bandItem, location, 2)).toBe(false)
  })

  it("highlights Band, not Profile, on a teammate's /members/:personId", () => {
    const location = { pathname: '/members/7', search: '' }

    expect(isNavItemActive(bandItem, location, 2)).toBe(true)
    expect(isNavItemActive(profileItem, location, 2)).toBe(false)
  })

  it('falls back to favoring Band when no viewerId is supplied', () => {
    const location = { pathname: '/members/2', search: '' }

    expect(isNavItemActive(bandItem, location)).toBe(true)
    expect(isNavItemActive(profileItem, location)).toBe(false)
  })

  it('still highlights Band on the plain /members list', () => {
    const location = { pathname: '/members', search: '' }

    expect(isNavItemActive(bandItem, location, 2)).toBe(true)
    expect(isNavItemActive(profileItem, location, 2)).toBe(false)
  })
})
