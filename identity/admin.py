from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import PersonChangeForm, PersonCreationForm
from .models import Person


@admin.register(Person)
class PersonAdmin(UserAdmin):
    model = Person
    add_form = PersonCreationForm
    form = PersonChangeForm

    ordering = ('email',)
    list_display = ('email', 'name', 'is_admin', 'is_active')
    list_filter = ('is_admin', 'is_active')
    search_fields = ('email', 'name')
    filter_horizontal = ('groups', 'user_permissions')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('name',)}),
        (
            'Permissions',
            {'fields': ('is_admin', 'is_active', 'groups', 'user_permissions')},
        ),
        ('Important dates', {'fields': ('last_login',)}),
    )
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'name', 'password1', 'password2'),
            },
        ),
    )
