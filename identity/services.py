"""The invite flow: the only way a Person becomes both allowlisted and
loggable-in, short of the Django admin panel (see issue #24).

`invite_person` creates the `Person` with an unusable password and emails a
one-time set-password link. The link's token comes from Django's
`default_token_generator` (a `PasswordResetTokenGenerator`), so it is
single-use (the hash incorporates the password field, invalidating it the
moment a password is set) and expires per `PASSWORD_RESET_TIMEOUT`.
"""

from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import Person


class EmailDeliveryError(Exception):
    """Raised when an invite email was not actually delivered to any recipient."""


def invite_person(*, name, email):
    """Create an allowlisted Person with no usable password and email them an invite.

    The Person creation and invite email are wrapped in a single atomic
    transaction: if the email fails to send (either `send_mail` raises, or
    it returns 0, meaning Django accepted the call but delivered nothing),
    the Person row is rolled back rather than left committed with an
    undelivered invite. This keeps `email`'s uniqueness constraint from
    blocking a retry after a failed invite.
    """
    with transaction.atomic():
        person = Person.objects.create_user(email=email, name=name, password=None)
        send_invite_email(person)
    return person


def build_set_password_url(person):
    """Build the absolute, single-use set-password link for a newly invited person."""
    uidb64 = urlsafe_base64_encode(force_bytes(person.pk))
    token = default_token_generator.make_token(person)
    path = reverse('identity:set-password-confirm', kwargs={'uidb64': uidb64, 'token': token})
    return urljoin(settings.SITE_URL, path)


def send_invite_email(person):
    """Email person their set-password link; raise EmailDeliveryError if nothing was sent.

    `send_mail` returns the number of messages successfully delivered (per
    Django's docs); a return of 0 means the call succeeded but nothing was
    actually sent, which we treat as a failure just like a raised exception.
    """
    set_password_url = build_set_password_url(person)
    subject = 'You have been invited to Rolling Sloans'
    body = render_to_string(
        'identity/invite_email.txt',
        {'person': person, 'set_password_url': set_password_url},
    )
    sent_count = send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [person.email])
    if not sent_count:
        raise EmailDeliveryError(f'invite email to {person.email} was not delivered')
