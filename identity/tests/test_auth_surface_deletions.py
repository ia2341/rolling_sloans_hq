"""Structural guard for the auth-surface collapse (issue #327), in the shape #315 established.

Names the deletions explicitly rather than asserting a route count, so a
later "restore for consistency" (e.g. re-adding `password-reset-done` as a
separate page) fails CI rather than passing review.
"""

from django.template import TemplateDoesNotExist
from django.template.loader import get_template
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

REMOVED_ROUTE_NAMES = (
    'identity:set-password-complete',
    'identity:password-reset-done',
    'identity:password-reset-confirm',
    'identity:password-reset-complete',
    'identity:password-change',
    'identity:password-change-done',
)

REMOVED_TEMPLATES = (
    'identity/password_reset_done.html',
    'identity/password_reset_complete.html',
    'identity/set_password_complete.html',
    'identity/password_reset_confirm.html',
    'identity/password_change_form.html',
    'identity/password_change_done.html',
)


class RemovedAuthRoutesTests(SimpleTestCase):
    def test_each_removed_route_name_no_longer_resolves(self):
        """None of the six collapsed-away route names should reverse to a URL any more."""
        for name in REMOVED_ROUTE_NAMES:
            with self.subTest(name=name), self.assertRaises(NoReverseMatch):
                reverse(name)


class RemovedAuthTemplatesTests(SimpleTestCase):
    def test_each_removed_template_no_longer_exists(self):
        """None of the six collapsed-away templates should be loadable any more."""
        for template_name in REMOVED_TEMPLATES:
            with self.subTest(template_name=template_name), self.assertRaises(TemplateDoesNotExist):
                get_template(template_name)
