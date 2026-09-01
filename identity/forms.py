from django import forms
from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from .models import Person


class PersonCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Person
        fields = ('email', 'name')


class PersonChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Person
        fields = '__all__'


class PersonInviteForm(forms.ModelForm):
    """`/manage/people/`'s invite form: collects name + email, leaving password creation to `invite_person()`."""

    class Meta:
        model = Person
        fields = ('name', 'email')
