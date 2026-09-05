import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'

import { ContextProvider } from '../api/ContextProvider'
import { EditSessionProvider } from '../shell/EditSessionContext'
import { PageTitleProvider } from '../shell/PageTitleContext'

/** Wraps a shell component with the providers `AppShell` normally supplies, for component-level tests. */
export function renderShell(
  children: ReactNode,
  initialEntries: string[] = ['/'],
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <ContextProvider>
        <EditSessionProvider>
          <PageTitleProvider>{children}</PageTitleProvider>
        </EditSessionProvider>
      </ContextProvider>
    </MemoryRouter>,
  )
}
