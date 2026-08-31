from django.contrib import admin

from .models import Membership, MembershipRole, Role, Semester


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
