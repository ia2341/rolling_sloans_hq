from django.contrib import admin

from .models import (
    Membership,
    MembershipRole,
    Rehearsal,
    Role,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)


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
    """No delete action: a Role is retired via is_active, never removed (issue #30)."""

    list_display = ('name', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('name',)
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False


class MembershipRoleInline(admin.TabularInline):
    """Edit a Membership's declared Roles inline on the Membership admin page."""

    model = MembershipRole
    extra = 1


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    """Admin for a Person's roster entry in one Semester, with declared Roles inline."""

    list_display = ('person', 'semester')
    list_filter = ('semester',)
    search_fields = ('person__name', 'person__email')
    inlines = (MembershipRoleInline,)


@admin.register(MembershipRole)
class MembershipRoleAdmin(admin.ModelAdmin):
    """Admin for a single declared Role on a Membership, for direct lookup/filtering."""

    list_display = ('membership', 'role')
    list_filter = ('role',)


class SongRoleRequirementInline(admin.TabularInline):
    """Edit a Song's target Role headcounts inline on the Song admin page (issue #33)."""

    model = SongRoleRequirement
    extra = 1


@admin.register(Song)
class SongAdmin(admin.ModelAdmin):
    """Admin edits change `position` directly to reorder a semester's setlist (issue #32)."""

    list_display = ('title', 'artist', 'semester', 'position', 'length')
    list_filter = ('semester',)
    search_fields = ('title', 'artist')
    ordering = ('semester', 'position')
    inlines = (SongRoleRequirementInline,)


@admin.register(SongRoleRequirement)
class SongRoleRequirementAdmin(admin.ModelAdmin):
    """Admin for a single Role headcount target on a Song, for direct lookup/filtering."""

    list_display = ('song', 'role', 'count')
    list_filter = ('role',)


@admin.register(SongRoleAssignment)
class SongRoleAssignmentAdmin(admin.ModelAdmin):
    """Admin for a single Person-on-Role-on-Song assignment, surfacing role mismatches (issue #35)."""

    list_display = ('song', 'role', 'person', 'is_role_mismatch')
    list_filter = ('is_role_mismatch', 'role')
    search_fields = ('person__name', 'person__email', 'song__title')
    readonly_fields = ('is_role_mismatch',)


@admin.register(Rehearsal)
class RehearsalAdmin(admin.ModelAdmin):
    """Grace periods and end_time can be left blank on create to inherit the Semester's defaults (issue #36)."""

    list_display = ('semester', 'date', 'start_time', 'end_time', 'is_full_setlist')
    list_filter = ('semester', 'is_full_setlist')
