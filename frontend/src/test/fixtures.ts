import type { AppContext } from '../api/types'

/** A member's `AppContext`, for tests that don't care about admin chrome. */
export function memberContext(overrides: Partial<AppContext> = {}): AppContext {
  return {
    viewer: {
      id: 1,
      name: 'Sam Rivera',
      email: 'sam@example.com',
      is_admin: false,
    },
    viewing_semester: {
      id: 10,
      name: 'Spring 2026',
      status: 'live',
      published_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    },
    live_semester: { id: 10, name: 'Spring 2026' },
    semester_warning: false,
    semester_options: [],
    pending_conflict_count: null,
    ...overrides,
  }
}

/** An admin's `AppContext`, viewing a non-live draft Semester by default. */
export function adminContext(overrides: Partial<AppContext> = {}): AppContext {
  return {
    viewer: {
      id: 2,
      name: 'Alex Kim',
      email: 'alex@example.com',
      is_admin: true,
    },
    viewing_semester: {
      id: 11,
      name: 'Fall 2026 (draft)',
      status: 'draft',
      published_at: null,
      updated_at: '2026-02-01T00:00:00Z',
    },
    live_semester: { id: 10, name: 'Spring 2026' },
    semester_warning: true,
    semester_options: [],
    pending_conflict_count: 3,
    ...overrides,
  }
}
