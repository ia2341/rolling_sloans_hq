import { PageHead } from '../components/ui/PageHead'
import { usePageTitle } from '../shell/PageTitleContext'

interface PlaceholderPageProps {
  title: string
  /** Names the ticket that owns this surface's real content. */
  owningIssue: string
}

/**
 * A stand-in for a route whose real content is a later ticket's (issue
 * #328 only owns the shell around it). Proves the nav destination exists
 * and is reachable; the page body itself is replaced ticket by ticket.
 */
export function PlaceholderPage({ title, owningIssue }: PlaceholderPageProps) {
  usePageTitle(title)
  return <PageHead title={title} subline={`Built by ${owningIssue}.`} />
}
