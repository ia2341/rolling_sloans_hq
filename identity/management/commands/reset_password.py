"""Break-glass password reset for the sole-active-admin lockout case (issue #487, ADR 0018).

Every other password reset goes through an admin clicking Reset password
on `/members/<pk>/` (`identity.services.apply_password_reset()`), which
refuses a self-reset and needs another active admin to exist and be
signed in to click it. That leaves exactly one case with no web-UI path
back in: the sole active admin locked out of their own account, with no
one else able to reset them. ADR 0018 decided that case is handled here,
outside the web app entirely, by an operator who already holds server/DB
access on the production host — a higher trust bar than any in-app
permission check could add, which is why this command carries none of
`apply_password_reset()`'s admin-count guardrail (there is nothing here
protecting *against* the operator; the guardrail exists to stop a web
session from talking itself into a lockout, and an operator with shell
access has already cleared that bar).

Generates a temp password the same way the web action does
(`identity.services.generate_temp_password()`), sets the same
`must_change_password` flag, and prints the plaintext to stdout for the
operator to relay by voice or text — never sent by email, matching the
rest of this ADR's decision.
"""

from django.core.management.base import BaseCommand, CommandError

from identity.models import Person
from identity.services import generate_temp_password


class Command(BaseCommand):
    help = (
        "Break-glass: reset a Person's password to a freshly generated temp password, "
        "flag must_change_password, and print the plaintext to stdout. Carries no "
        "admin-count guardrail; for the sole-active-admin lockout case (ADR 0018)."
    )

    def add_arguments(self, parser):
        """Register the single positional `email` argument identifying the Person to reset."""
        parser.add_argument('email', help="The Person's email address.")

    def handle(self, *args, **options):
        """Look up the Person by email, set a fresh temp password, flag must_change_password, and print the plaintext."""
        email = options['email']
        try:
            person = Person.objects.get(email__iexact=email)
        except Person.DoesNotExist as error:
            raise CommandError(f'No Person found with email {email!r}') from error

        temp_password = generate_temp_password()
        person.set_password(temp_password)
        person.must_change_password = True
        person.save(update_fields=['password', 'must_change_password'])

        self.stdout.write(self.style.SUCCESS(f'Password reset for {person.email}.'))
        self.stdout.write(f'Temp password: {temp_password}')
