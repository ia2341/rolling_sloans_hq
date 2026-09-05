from typing import ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class PersonManager(BaseUserManager):
    use_in_migrations = True

    def _create_person(self, email, password, **extra_fields):
        """
        Create and save a person with a normalized email address and configured password.
        
        Parameters:
            email (str): The person's email address.
            password (str): The password to set, or a falsey value to set an unusable password.
            **extra_fields: Additional fields for the person.
        
        Returns:
            Person: The newly created person.
        """
        if not email:
            raise ValueError('Person must have an email address')
        person = self.model(email=self.normalize_email(email), **extra_fields)
        if password:
            person.set_password(password)
        else:
            person.set_unusable_password()
        person.save(using=self._db)
        return person

    def create_user(self, email, password=None, **extra_fields):
        """
        Create a regular person account.
        
        Parameters:
        	email (str): The person's email address.
        	password (str, optional): The password for the account.
        	extra_fields (dict): Additional person fields.
        
        Returns:
        	Person: The newly created person.
        """
        extra_fields.setdefault('is_admin', False)
        return self._create_person(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Create an administrative person account.
        
        Parameters:
            email: The person's email address.
            password: The person's password.
            **extra_fields: Additional fields for the person.
        
        Returns:
            Person: The created administrative person.
        """
        extra_fields['is_admin'] = True
        return self._create_person(email, password, **extra_fields)


class Person(AbstractBaseUser, PermissionsMixin):
    """The persistent identity/auth record every part of the app authenticates against.

    No separate Group/Permission objects back `is_admin` — save() mirrors it
    onto `is_staff`/`is_superuser` directly, per the Identity & Auth spec (#13).
    """

    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    is_admin = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = PersonManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: ClassVar[list[str]] = ['name']

    def save(self, *args, **kwargs):
        """
        Save the person while synchronizing administrative, staff, and superuser status.
        
        When ``is_admin`` is included in ``update_fields``, the corresponding staff and
        superuser fields are saved as well.
        """
        self.is_staff = self.is_admin
        self.is_superuser = self.is_admin

        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'is_admin' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'is_staff', 'is_superuser'}

        super().save(*args, **kwargs)

    def __str__(self):
        """Return the person's email address as a string."""
        return self.email


class LoginAttempt(models.Model):
    """One row per sign-in POST, win or lose (#327's limit one: failed sign-ins).

    Keyed on the address *as submitted*, not a resolved `Person` FK — a
    failed attempt may name an address with no account at all, which is
    exactly the case a guessing attack produces. Counting rows in a window
    is deliberate over a cache: `CACHES` is unconfigured, so Django falls
    back to per-process `LocMemCache`, which would silently multiply any
    limit by the gunicorn worker count (the reasoning #307 established for
    the login-code work this ticket reverses).
    """

    email = models.EmailField()
    ip_address = models.GenericIPAddressField()
    was_successful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes: ClassVar[list] = [
            models.Index(fields=['email', 'created_at']),
            models.Index(fields=['ip_address', 'created_at']),
        ]


class AuthEmailRequest(models.Model):
    """One row per outbound auth email requested: a reset request or a `resend_invite()` (#327's limit two).

    This limit is about Resend quota and sending reputation, not
    enumeration: an unauthenticated endpoint that triggers third-party
    email is a way to burn both, which would take down all authentication,
    invites included. Row-counted for the same worker-count reason as
    `LoginAttempt`.
    """

    email = models.EmailField()
    ip_address = models.GenericIPAddressField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes: ClassVar[list] = [
            models.Index(fields=['email', 'created_at']),
            models.Index(fields=['ip_address', 'created_at']),
        ]
