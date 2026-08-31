from django.contrib import admin

from .models import Role, Semester


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'default_rehearsal_duration_minutes',
        'default_setup_grace_minutes',
        'default_teardown_grace_minutes',
        'default_song_slot_count',
    )
    search_fields = ('name',)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
