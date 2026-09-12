import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  applyThemePreference,
  cacheThemePreference,
  readCachedThemePreference,
} from './theme'

describe('theme', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  afterEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.theme
  })

  describe('applyThemePreference', () => {
    it('sets data-theme for an explicit light/dark choice', () => {
      applyThemePreference('dark')
      expect(document.documentElement.dataset.theme).toBe('dark')

      applyThemePreference('light')
      expect(document.documentElement.dataset.theme).toBe('light')
    })

    it('clears data-theme for system, falling through to prefers-color-scheme', () => {
      applyThemePreference('dark')

      applyThemePreference('system')

      expect(document.documentElement.dataset.theme).toBeUndefined()
    })
  })

  describe('cacheThemePreference / readCachedThemePreference', () => {
    it('round-trips a cached preference', () => {
      cacheThemePreference('dark')

      expect(readCachedThemePreference()).toBe('dark')
    })

    it('defaults to system when nothing is cached', () => {
      expect(readCachedThemePreference()).toBe('system')
    })

    it('defaults to system for a corrupted cached value', () => {
      localStorage.setItem('rs-theme-preference', 'not-a-real-theme')

      expect(readCachedThemePreference()).toBe('system')
    })
  })
})
