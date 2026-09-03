"""Template context every page in the nav shell needs, regardless of which view rendered it."""

from scheduling.services import semester_banner_for


def semester_banner(request):
    """Expose the non-live Semester warning to `templates/base.html`, so no page can forget to render it (issue #169).

    Deliberately a context processor rather than per-view context: the
    banner is the guard against an admin silently editing last semester's
    setlist, and a guard a view has to opt into is a guard a view can skip.
    A member — and any request without a resolved Semester or session —
    gets None, and the shell renders nothing.
    """
    return {'semester_banner': semester_banner_for(request)}
