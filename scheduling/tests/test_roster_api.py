"""`/api/members/roster/*`: the Roster editor's read/preview/save/candidates/roles/resend-invite surface (issue #336, ADR 0008)."""

import json

from django.core import mail
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from identity.models import Person
from scheduling.factories import (
    MembershipFactory,
    RoleFactory,
    SemesterFactory,
)
from scheduling.models import Membership, MembershipRole
from scheduling.tests.api_test_helpers import (
    admin_client,
    member_client,
    select,
)
from scheduling.tests.preview_helpers import assert_preview_writes_nothing


def _roster_url():
    """Return the Roster editor read `/api/` endpoint's URL."""
    return reverse('api-roster-edit')


def _preview_url():
    """Return the Roster Preview `/api/` endpoint's URL."""
    return reverse('api-roster-preview')


def _save_url():
    """Return the Roster Save `/api/` endpoint's URL."""
    return reverse('api-roster-save')


def _candidates_url():
    """Return the `+ Add people` sheet's candidates `/api/` endpoint's URL."""
    return reverse('api-roster-candidates')


def _declare_role_url():
    """Return the `+ Role` chip's declare-a-Role `/api/` endpoint's URL."""
    return reverse('api-roster-declare-role')


def _resend_invite_url(pk):
    """Return the resend-invite `/api/` endpoint's URL for Person `pk`."""
    return reverse('api-roster-resend-invite', args=[pk])


def _post_json(test_case, url, body):
    """POST `body` (a dict) as a JSON request body and return the parsed response envelope."""
    response = test_case.client.post(url, data=json.dumps(body), content_type='application/json')
    return response, json.loads(response.content)


def _valid_body(semester, entries=None, removed_person_ids=None, invites=None):
    """Build a well-formed `/api/members/roster/{preview,save}/` request body for `semester`."""
    return {
        'semester_id': semester.pk,
        'semester_updated_at': semester.updated_at.isoformat(),
        'entries': entries or [],
        'removed_person_ids': removed_person_ids or [],
        'invites': invites or [],
    }


@override_settings(SECURE_SSL_REDIRECT=False)
class AccessControlTests(TestCase):
    """Every Roster editor endpoint gates identically to every other `AdminApiView`/`AdminPreviewApiView`."""

    def setUp(self):
        """Build a Semester so a request has something to resolve against."""
        self.semester = SemesterFactory()

    def test_anonymous_roster_get_is_401(self):
        """An anonymous GET to the Roster read endpoint answers the documented JSON 401, never a redirect."""
        response = self.client.get(_roster_url())

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_roster_get_is_403(self):
        """A logged-in non-admin's GET to the Roster read endpoint is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.get(_roster_url())

        self.assertEqual(response.status_code, 403)

    def test_anonymous_candidates_get_is_401(self):
        """An anonymous GET to the candidates endpoint answers 401."""
        response = self.client.get(_candidates_url())

        self.assertEqual(response.status_code, 401)

    def test_non_admin_candidates_get_is_403(self):
        """A logged-in non-admin's GET to the candidates endpoint is rejected with 403."""
        member_client(self)

        response = self.client.get(_candidates_url())

        self.assertEqual(response.status_code, 403)

    def test_anonymous_declare_role_post_is_401(self):
        """An anonymous POST to the declare-Role endpoint answers 401."""
        response = self.client.post(_declare_role_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)

    def test_non_admin_declare_role_post_is_403(self):
        """A logged-in non-admin's POST to the declare-Role endpoint is rejected with 403."""
        member_client(self)

        response = self.client.post(_declare_role_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_anonymous_resend_invite_post_is_401(self):
        """An anonymous POST to resend-invite answers 401."""
        person = Person.objects.create(name='Someone', email='someone@example.com')

        response = self.client.post(_resend_invite_url(person.pk))

        self.assertEqual(response.status_code, 401)

    def test_non_admin_resend_invite_post_is_403(self):
        """A logged-in non-admin's POST to resend-invite is rejected with 403."""
        member_client(self)
        person = Person.objects.create(name='Someone', email='someone@example.com')

        response = self.client.post(_resend_invite_url(person.pk))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_preview_post_is_401(self):
        """An anonymous POST to Preview answers the documented JSON 401, never a redirect."""
        response = self.client.post(_preview_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_anonymous_save_post_is_401(self):
        """An anonymous POST to Save answers the documented JSON 401, never a redirect."""
        response = self.client.post(_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('Location', response)

    def test_non_admin_preview_post_is_403(self):
        """A logged-in non-admin's POST to Preview is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_preview_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_non_admin_save_post_is_403(self):
        """A logged-in non-admin's POST to Save is rejected with the documented JSON 403."""
        member_client(self)

        response = self.client.post(_save_url(), data='{}', content_type='application/json')

        self.assertEqual(response.status_code, 403)

    def test_preview_get_is_not_allowed(self):
        """A GET to Preview is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_preview_url())

        self.assertEqual(response.status_code, 405)

    def test_save_get_is_not_allowed(self):
        """A GET to Save is rejected -- it is POST-only."""
        admin_client(self)

        response = self.client.get(_save_url())

        self.assertEqual(response.status_code, 405)


@override_settings(SECURE_SSL_REDIRECT=False)
class RosterReadTests(TestCase):
    """`GET /api/members/roster/` returns every Membership, active and must-change-password alike."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with one active member and one pending invite."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.role = RoleFactory()

    def test_roster_read_lists_active_and_must_change_password_members_with_no_email(self):
        """The read model lists every Membership, distinguishes credential status, and never carries email (ADR 0005, #482)."""
        from identity.factories import PersonFactory

        active_person = PersonFactory(name='Active Person', password='a-strong-test-password-123')
        active_membership = MembershipFactory(person=active_person, semester=self.semester)
        MembershipRole.objects.create(membership=active_membership, role=self.role)
        must_change_person = PersonFactory(name='Must Change Person', must_change_password=True)
        MembershipFactory(person=must_change_person, semester=self.semester)

        response = self.client.get(_roster_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['active_count'], 1)
        self.assertEqual(envelope['data']['invited_count'], 1)
        names = {member['name'] for member in envelope['data']['members']}
        self.assertEqual(names, {'Active Person', 'Must Change Person'})
        for member in envelope['data']['members']:
            self.assertNotIn('email', member)
        must_change_row = next(m for m in envelope['data']['members'] if m['name'] == 'Must Change Person')
        active_row = next(m for m in envelope['data']['members'] if m['name'] == 'Active Person')
        self.assertEqual(must_change_row['invite_status'], 'must_change_password')
        self.assertEqual(active_row['invite_status'], 'active')

@override_settings(SECURE_SSL_REDIRECT=False)
class RosterReadNoSemesterTests(TestCase):
    """With no Semester in existence at all, the read endpoint returns the documented empty shape rather than erroring."""

    def test_roster_read_with_no_semester_at_all_returns_empty_shape(self):
        """An admin with nothing to view yet gets the empty shape, not a 500 or a 404."""
        admin_client(self)

        response = self.client.get(_roster_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(envelope['data']['semester_id'])
        self.assertEqual(envelope['data']['members'], [])


@override_settings(SECURE_SSL_REDIRECT=False)
class CandidatesTests(TestCase):
    """`GET /api/members/roster/candidates/` returns the `+ Add people` sheet's two ticket-source lists."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_candidates_lists_unrostered_people(self):
        """An active Person holding no Membership in the viewing Semester appears in unrostered_people."""
        from identity.factories import PersonFactory

        PersonFactory(name='Not Yet Rostered', password='a-strong-test-password-123')

        response = self.client.get(_candidates_url())
        envelope = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        names = {person['name'] for person in envelope['data']['unrostered_people']}
        self.assertIn('Not Yet Rostered', names)
        self.assertIsNone(envelope['data']['import_source_semester_name'])


@override_settings(SECURE_SSL_REDIRECT=False)
class DeclareRoleTests(TestCase):
    """`POST /api/members/roster/roles/` get-or-creates a Role by name."""

    def setUp(self):
        """Log in a synthetic admin."""
        admin_client(self)

    def test_declaring_a_new_role_creates_it(self):
        """A previously unseen name creates a new Role and reports created: true."""
        response, envelope = _post_json(self, _declare_role_url(), {'name': 'Trombone'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(envelope['data']['role']['name'], 'Trombone')
        self.assertTrue(envelope['data']['created'])

    def test_blank_name_is_a_400(self):
        """A blank/missing name is rejected with a 400, not a created Role."""
        response, envelope = _post_json(self, _declare_role_url(), {'name': '  '})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(envelope['error'], 'invalid_name')


@override_settings(SECURE_SSL_REDIRECT=False)
class ResendInviteTests(TestCase):
    """`POST /api/members/roster/<pk>/resend-invite/` re-sends a pending invite."""

    def setUp(self):
        """Log in a synthetic admin."""
        admin_client(self)

    def test_resend_invite_to_a_pending_person_succeeds(self):
        """Resending to a Person with no usable password succeeds and sends mail."""
        from identity.factories import PersonFactory

        pending = PersonFactory(name='Pending Person', password=None, email='pending@example.com')

        response, envelope = _post_json(self, _resend_invite_url(pending.pk), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_invite_to_an_active_person_is_refused(self):
        """Resending to a Person who already has a usable password is refused with ok: false."""
        from identity.factories import PersonFactory

        active = PersonFactory(name='Active Person', password='a-strong-test-password-123')

        response, envelope = _post_json(self, _resend_invite_url(active.pk), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])

    def test_resend_invite_to_a_deactivated_person_is_refused(self):
        """Resending to a deactivated Person is refused with ok: false, never an unhandled 500 (issue #469 review)."""
        from identity.factories import PersonFactory

        deactivated = PersonFactory(name='Deactivated Person', password=None, is_active=False)

        response, envelope = _post_json(self, _resend_invite_url(deactivated.pk), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertEqual(len(mail.outbox), 0)

    def test_resend_invite_reports_a_clean_failure_when_the_email_backend_raises(self):
        """A production-shaped `AnymailError` (e.g. a rejected API key) from `send_mail()` surfaces as `ok: false`, never a 500 (issue #409)."""
        from unittest import mock

        from anymail.exceptions import AnymailAPIError

        from identity.factories import PersonFactory

        pending = PersonFactory(name='Pending Person', password=None, email='pending@example.com')

        with mock.patch('identity.services.send_mail', side_effect=AnymailAPIError('bad api key')):
            response, envelope = _post_json(self, _resend_invite_url(pending.pk), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertEqual(len(mail.outbox), 0)


@override_settings(SECURE_SSL_REDIRECT=False)
class PersonPageInviteTests(TestCase):
    """`POST /api/members/<pk>/invite/`: the legacy email-invite action (issue #397), kept but no longer reachable from the SPA (issue #482, ADR 0018)."""

    def setUp(self):
        """Log in a synthetic admin."""
        admin_client(self)

    def test_inviting_a_not_yet_invited_person_sends_mail(self):
        """Inviting a Person `add_person()` created sends the legacy invite email. `invite_status` no longer tracks this path (#482) -- it reads 'active' either way, since `must_change_password` is untouched by it."""
        from identity.services import add_person

        person = add_person(name='Not Yet Invited Person', email='not-yet-invited@example.com')

        response, envelope = _post_json(self, reverse('api-member-invite', args=[person.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(envelope['data']['invite_status'], 'active')

    def test_inviting_an_active_person_is_refused(self):
        """Inviting a Person who already has a usable password is refused with ok: false."""
        from identity.factories import PersonFactory

        active = PersonFactory(name='Active Person', password='a-strong-test-password-123')

        response, envelope = _post_json(self, reverse('api-member-invite', args=[active.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])

    def test_inviting_a_deactivated_person_is_refused(self):
        """Inviting a deactivated Person is refused with ok: false, never an unhandled 500 (issue #469 review)."""
        from identity.factories import PersonFactory

        deactivated = PersonFactory(name='Deactivated Person', password=None, is_active=False)

        response, envelope = _post_json(self, reverse('api-member-invite', args=[deactivated.pk]), {})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewValidBufferTests(TestCase):
    """A valid Roster edit Buffer's Preview renders Fallout, echoes `values`, writes nothing and sends no mail."""

    def setUp(self):
        """Log in a synthetic admin against a Semester with an existing member."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        from identity.factories import PersonFactory

        self.kept = PersonFactory(name='Kept Person')
        MembershipFactory(person=self.kept, semester=self.semester)

    def test_valid_buffer_with_a_new_person_previews_ok_and_writes_and_mails_nothing(self):
        """A Buffer with a staged new Person previews `ok: true`, lists them in pending_created, and creates no Person (issue #482)."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'New Invitee', 'email': 'new-invitee@example.com'},
        ])

        response = assert_preview_writes_nothing(
            self, _preview_url(), models_to_check=[Person, Membership], semester=self.semester, json_body=body,
        )
        envelope = json.loads(response.content)

        self.assertTrue(envelope['ok'])
        self.assertIn('New Invitee', envelope['fallout']['pending_created'])
        self.assertEqual(envelope['values']['invites'][0]['email'], 'new-invitee@example.com')
        self.assertFalse(Person.objects.filter(email='new-invitee@example.com').exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_preview_never_reveals_a_temp_password(self):
        """A Preview's echoed values never carry a temp password field anywhere in the response (issue #482)."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'New Invitee', 'email': 'new-invitee@example.com'},
        ])

        response = assert_preview_writes_nothing(
            self, _preview_url(), models_to_check=[Person, Membership], semester=self.semester, json_body=body,
        )

        self.assertNotIn(b'temp_password', response.content)


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewInvalidBufferTests(TestCase):
    """A malformed Roster Buffer previews `ok: false` with per-row errors, echoing every submitted value."""

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_invite_reusing_an_existing_email_previews_ok_false(self):
        """An invite whose email already belongs to a Person is rejected with a row error, not a save."""
        from identity.factories import PersonFactory

        existing = PersonFactory(email='taken@example.com')
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'Somebody', 'email': existing.email},
        ])

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('email', envelope['errors']['invite-1'])

    def test_invite_missing_name_previews_ok_false(self):
        """An invite row with a blank name is rejected with a row error."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': '', 'email': 'blank-name@example.com'},
        ])

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertIn('name', envelope['errors']['invite-1'])


@override_settings(SECURE_SSL_REDIRECT=False)
class WrongSemesterTests(TestCase):
    """A `semester_id` that doesn't match the viewing Semester hard-fails on both endpoints."""

    def setUp(self):
        """Log in a synthetic admin viewing one Semester, with a second Semester the Buffer will wrongly claim."""
        admin_client(self)
        self.viewing_semester = SemesterFactory()
        self.other_semester = SemesterFactory()
        select(self, self.viewing_semester)

    def test_wrong_semester_id_previews_a_4xx(self):
        """Preview answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _preview_url(), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')

    def test_wrong_semester_id_save_is_a_4xx(self):
        """Save answers a wrong `semester_id` with a 4xx, not a 200 Validation Error."""
        body = _valid_body(self.other_semester)

        response, envelope = _post_json(self, _save_url(), body)

        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        self.assertEqual(envelope['error'], 'wrong_semester')


@override_settings(SECURE_SSL_REDIRECT=False)
class StaleSemesterTests(TestCase):
    """A stale `semester_updated_at` is reported, never refused (ADR 0008), differently on Preview vs. Save."""

    def setUp(self):
        """Log in a synthetic admin against a Semester, and build a stamp a year behind reality."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        self.stale_stamp = self.semester.updated_at.replace(year=self.semester.updated_at.year - 1)

    def _stale_body(self):
        """Build a well-formed Buffer body whose `semester_updated_at` is the stale (year-behind) stamp."""
        return {
            'semester_id': self.semester.pk,
            'semester_updated_at': self.stale_stamp.isoformat(),
            'entries': [],
            'removed_person_ids': [],
            'invites': [],
        }

    def test_stale_preview_reports_is_stale_true_with_fallout_still_computed(self):
        """Preview against a stale stamp still computes Fallout and reports `is_stale: true`, `ok: true`."""
        response, envelope = _post_json(self, _preview_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertTrue(envelope['fallout']['is_stale'])

    def test_stale_save_is_refused_without_corrupting_data(self):
        """Save against a stale stamp reports `ok: false` (not a hard 4xx) and creates no Person."""
        count_before = Person.objects.count()

        response, envelope = _post_json(self, _save_url(), self._stale_body())

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertEqual(Person.objects.count(), count_before)


@override_settings(SECURE_SSL_REDIRECT=False)
class SelfRemovalTests(TestCase):
    """An admin cannot remove their own Membership through Save (issue #336 user story 15)."""

    def test_self_removal_save_is_refused(self):
        """Save refuses a Buffer removing the requesting admin's own Person, reporting ok: false."""
        admin = admin_client(self)
        semester = SemesterFactory()
        select(self, semester)
        MembershipFactory(person=admin, semester=semester)
        body = _valid_body(semester, removed_person_ids=[admin.pk])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope['ok'])
        self.assertTrue(envelope['non_field_errors'])
        self.assertTrue(Membership.objects.filter(person=admin, semester=semester).exists())


@override_settings(SECURE_SSL_REDIRECT=False)
class SaveCommitsTests(TestCase):
    """A valid Save actually persists the Buffer, including creating a new Person with a real temp password (issue #482, ADR 0018).

    Plain `TestCase`: creation reaches no external service, so unlike the
    retired email-invite path there's no `transaction.on_commit()`
    deferral that needs a real commit to observe.
    """

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)

    def test_valid_save_with_a_new_person_creates_them_with_a_temp_password_and_sends_no_mail(self):
        """A Save with a staged new Person creates them with a real, usable temp password, rosters them, and sends no mail at all."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'Brand New Member', 'email': 'brand-new@example.com'},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        person = Person.objects.get(email='brand-new@example.com')
        self.assertEqual(person.name, 'Brand New Member')
        self.assertTrue(person.has_usable_password())
        self.assertTrue(person.must_change_password)
        self.assertTrue(Membership.objects.filter(person=person, semester=self.semester).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_valid_save_creating_several_people_reveals_a_temp_password_for_each(self):
        """A single Save that creates multiple people returns one temp_passwords entry per new Person, each usable on their own row (issue #482)."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'First New Member', 'email': 'first-new@example.com'},
            {'row_key': 'invite-2', 'name': 'Second New Member', 'email': 'second-new@example.com'},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        temp_passwords = {entry['email']: entry['temp_password'] for entry in envelope['values']['temp_passwords']}
        self.assertEqual(set(temp_passwords), {'first-new@example.com', 'second-new@example.com'})
        first = Person.objects.get(email='first-new@example.com')
        second = Person.objects.get(email='second-new@example.com')
        self.assertTrue(first.check_password(temp_passwords['first-new@example.com']))
        self.assertTrue(second.check_password(temp_passwords['second-new@example.com']))
        self.assertNotEqual(temp_passwords['first-new@example.com'], temp_passwords['second-new@example.com'])
        self.assertTrue(Membership.objects.filter(person=first, semester=self.semester).exists())
        self.assertTrue(Membership.objects.filter(person=second, semester=self.semester).exists())

    def test_valid_save_reveals_the_temp_password_in_values(self):
        """Save's response carries the real, one-time temp password for each Person just created (issue #482)."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'Brand New Member', 'email': 'brand-new@example.com'},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        temp_passwords = envelope['values']['temp_passwords']
        self.assertEqual(len(temp_passwords), 1)
        self.assertEqual(temp_passwords[0]['email'], 'brand-new@example.com')
        person = Person.objects.get(email='brand-new@example.com')
        self.assertTrue(person.check_password(temp_passwords[0]['temp_password']))

    def test_valid_save_with_no_new_people_carries_an_empty_temp_passwords_list(self):
        """A Save that only rosters an existing Person still carries `values.temp_passwords`, just empty."""
        from identity.factories import PersonFactory

        existing = PersonFactory(name='Existing Person')
        body = _valid_body(self.semester, entries=[
            {'row_key': 'row-1', 'person_id': existing.pk, 'name': existing.name},
        ])

        response, envelope = _post_json(self, _save_url(), body)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope['ok'])
        self.assertEqual(envelope['values']['temp_passwords'], [])


@override_settings(SECURE_SSL_REDIRECT=False)
class PreviewThenSaveRoundTripTests(TransactionTestCase):
    """Regression test for issue #409: Preview's echoed `updated_at`, fed straight back into Save, must not falsely read as stale.

    Reproduces the reported bug exactly: an admin opens the Save dialog
    (which auto-runs a Preview, `usePreviewOnOpen`), then clicks Save —
    the SPA's `confirmSave()` sends whatever `updated_at` the shared
    context currently holds, which is the value the *Preview* response's
    envelope carried. With zero concurrent edits, that round trip must
    still match the real DB row when Save runs its own staleness check.
    Before issue #409's fix this failed for two independent reasons that
    had to be fixed together: `apply_roster_edits()` (run for real by
    Preview, then rolled back) bumps `Semester.updated_at`, and that
    bumped-but-about-to-be-discarded value leaked into the Preview
    response's `context` because `PreviewMixin` built it mid-transaction
    (Cause A); and `_serialize_semester()` emitted `updated_at` as a raw
    `datetime`, which `DjangoJSONEncoder` truncates to millisecond
    precision on the wire, so even a correctly-timed read echoes back a
    value that no longer equals the full-precision DB stamp once
    round-tripped through `parse_datetime()` (Cause B).
    """

    # Restores the seeded RoleGroup catalog (issue #457) after this test's
    # teardown flush, which would otherwise truncate it for every test that
    # runs after this one in the same process.
    serialized_rollback = True

    def setUp(self):
        """Log in a synthetic admin against a fresh Semester with one existing member."""
        admin_client(self)
        self.semester = SemesterFactory()
        select(self, self.semester)
        from identity.factories import PersonFactory

        self.kept = PersonFactory(name='Kept Person')
        MembershipFactory(person=self.kept, semester=self.semester)

    def test_saving_with_previews_echoed_updated_at_succeeds_with_no_concurrent_edits(self):
        """Preview then Save, using exactly the `updated_at` Preview's own response echoed back, must succeed."""
        body = _valid_body(self.semester, invites=[
            {'row_key': 'invite-1', 'name': 'New Invitee', 'email': 'new-invitee@example.com'},
        ])

        _preview_response, preview_envelope = _post_json(self, _preview_url(), body)
        self.assertTrue(preview_envelope['ok'])
        echoed_updated_at = preview_envelope['context']['viewing_semester']['updated_at']

        save_body = {**body, 'semester_updated_at': echoed_updated_at}
        save_response, save_envelope = _post_json(self, _save_url(), save_body)

        self.assertEqual(save_response.status_code, 200)
        self.assertTrue(save_envelope['ok'], save_envelope.get('non_field_errors'))
        self.assertTrue(Person.objects.filter(email='new-invitee@example.com').exists())
