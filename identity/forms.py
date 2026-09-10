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
