from django.contrib import admin

from .models import (
    Conflict,
    ConflictWindow,
    Membership,
    MembershipRole,
    Rehearsal,
    RehearsalSong,
    Role,
    Semester,
    Song,
    SongRoleAssignment,
    SongRoleRequirement,
)


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    """Admin for a Semester, surfacing the lifecycle so a new one is visibly a draft until it is published (ADR-0010)."""

    list_display = (
        'name',
        'published_at',
        'created_at',
        'default_rehearsal_duration_minutes',
        'default_setup_grace_minutes',
        'default_teardown_grace_minutes',
        'default_song_slot_count',
        'default_arrival_buffer_minutes',
        'default_departure_buffer_minutes',
    )
    search_fields = ('name',)
    readonly_fields = ('created_at',)


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


class RehearsalSongInline(admin.TabularInline):
    """Edit a Rehearsal's scheduled Songs inline; start_time/end_time are computed on save (issue #37)."""

    model = RehearsalSong
    extra = 1
    readonly_fields = ('start_time', 'end_time')


@admin.register(Rehearsal)
class RehearsalAdmin(admin.ModelAdmin):
    """Grace periods and end_time can be left blank on create to inherit the Semester's defaults (issue #36)."""

    list_display = ('semester', 'date', 'start_time', 'end_time', 'is_full_setlist')
    list_filter = ('semester', 'is_full_setlist')
    inlines = (RehearsalSongInline,)


@admin.register(RehearsalSong)
class RehearsalSongAdmin(admin.ModelAdmin):
    """Admin for a single Song's timed slot within a Rehearsal, for direct lookup/filtering (issue #37)."""

    list_display = ('rehearsal', 'order', 'song', 'slot_count', 'start_time', 'end_time')
    list_filter = ('rehearsal__semester',)
    search_fields = ('song__title',)
    readonly_fields = ('start_time', 'end_time')


class ConflictWindowInline(admin.TabularInline):
    """Edit a partial Conflict's unavailable time ranges inline on the Conflict admin page (issue #49)."""

    model = ConflictWindow
    extra = 1


@admin.register(Conflict)
class ConflictAdmin(admin.ModelAdmin):
    """Admin for a Person's declared unavailability on a Rehearsal, editable in place (issue #48)."""

    list_display = ('person', 'rehearsal', 'type', 'updated_at')
    list_filter = ('type', 'rehearsal__semester')
    search_fields = ('person__name', 'person__email')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (ConflictWindowInline,)


@admin.register(ConflictWindow)
class ConflictWindowAdmin(admin.ModelAdmin):
    """Admin for a single unavailable time range within a partial Conflict, for direct lookup/filtering (issue #49)."""

    list_display = ('conflict', 'unavailable_start', 'unavailable_end')
    list_filter = ('conflict__rehearsal__semester',)
