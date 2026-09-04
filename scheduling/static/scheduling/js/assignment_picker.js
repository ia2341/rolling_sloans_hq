// The assignment grid's edit-mode buffer (issue #210) plus the per-cell "+" popover picker
// (issue #211), extended with the Backup half of that same picker and buffer (issue #216).
// Every kind of buffered change -- ✕'d standing assignments, ✕'d Backups, picked standing
// assignments, and picked Backups (each optionally with a "covering for" pick) -- lives in
// this one Alpine component so "Save Changes" commits all of it together.
//
// The picker's fetched HTML is injected via x-html, which Alpine never re-scans for
// directives, so its person rows carry no @click of their own -- clicking one is caught by
// event delegation on the static <dialog> wrapper instead (a plain DOM click bubbles through
// injected content exactly like any other node).
//
// The dialog itself carries the Fallout Preview's hx-* attributes (issue #212), firing on the
// dialog's native "close" event -- however the popover closed (a pick, Cancel, or Escape) -- and
// never per pick inside an open popover, since the popover is the bounded edit gesture (ADR
// 0008). hx-include reads the whole edit form's current buffer, so the fired Preview always
// reflects every pending removal and pick, not just the one that just happened.
document.addEventListener('alpine:init', () => {
  // initialRemoved/initialAdded/initialEditing re-seed the buffer after a blocked Save re-renders the
  // page (issue #212) -- a Validation Error must never cost the rest of an admin's pending edits.
  // initialRemovedBackups/initialAddedBackups/initialBackupCoveringFor do the same for the Backup
  // half of the buffer (issue #216 review): a blocked Save must not silently drop a pending Backup
  // removal, a pending Backup pick, or a pending covering_for change on an already-persisted Backup.
  Alpine.data('assignmentGrid', (
    pickerUrlTemplate,
    initialRemoved = [],
    initialAdded = [],
    initialEditing = false,
    initialRemovedBackups = [],
    initialAddedBackups = [],
    initialBackupCoveringFor = {},
    initialPrefillBackup = null,
  ) => ({
    editing: initialEditing,
    removed: [...initialRemoved],
    added: [...initialAdded],
    removedBackups: [...initialRemovedBackups],
    addedBackups: [...initialAddedBackups],
    pendingBackupCoveringFor: { ...initialBackupCoveringFor },
    prefillBackup: initialPrefillBackup,
    pickerSongId: null,
    pickerRoleId: null,
    pickerRehearsalSongId: null,
    pickerHtml: '',
    pickerError: '',
    pickerRequestToken: 0,
    cellStandingAssignees: JSON.parse(document.getElementById('cell-standing-assignees-data').textContent),
    pickerUrlTemplate: pickerUrlTemplate || '',
    extraRoles: [],
    selectedRoleToAdd: '',
    addableRoles: [],
    previewError: '',

    // "+ Add role" (issue #213): every addable Role (active, not already a column),
    // read once from the json_script the server rendered -- a plain data island, not
    // an Alpine.data() init arg, since a Role name could contain a quote or apostrophe.
    //
    // pendingBackupCoveringFor (issue #216 review) restores a blocked Save's pending pick onto an
    // already-persisted Backup chip's "covering for" <select> -- that <select>'s server-rendered
    // `selected` option reflects only the last-*saved* covering_for, not the just-submitted pick,
    // since the chip comes from a fresh assignment_matrix_for() read, not from the pending Buffer.
    init() {
      const dataEl = document.getElementById('addable-roles-data');
      this.addableRoles = dataEl ? JSON.parse(dataEl.textContent) : [];
      Object.entries(this.pendingBackupCoveringFor).forEach(([backupId, personId]) => {
        const select = document.querySelector(`select[name="backup_covering_for_${backupId}"]`);
        if (select) {
          select.value = personId;
        }
      });
      this.openPrefilledBackupCell();
    },

    // Arriving from the adjudication table's advisory door (issue #195): opens the targeted
    // cell's picker straight away, so the Backup section is right there rather than making the
    // admin re-find the (Song, Role) the overlap named.
    openPrefilledBackupCell() {
      if (!this.prefillBackup) {
        return;
      }
      // Reached only from init() (Alpine's own automatic call, with the
      // component root as the evaluating element -- there's no x-init on the
      // grid's root), so `$el` would be safe here too, but use `$root`
      // anyway (issue #290) so "component furniture is always reached via
      // `$root`" holds with no exceptions to remember.
      this.editing = true;
      const button = this.$root.querySelector(
        `.assignment-cell-add[data-song-id="${this.prefillBackup.songId}"][data-role-id="${this.prefillBackup.roleId}"]`,
      );
      if (button) {
        button.click();
      }
    },

    cancelEditing() {
      this.editing = false;
      this.removed = [];
      this.added = [];
      this.removedBackups = [];
      this.addedBackups = [];
      this.extraRoles = [];
      this.selectedRoleToAdd = '';
    },

    // Roles offered in the "+ Add role" <select>: every addable Role not already
    // added as an extra column this view (a Role becomes a real column, sourced
    // from the server, only after Save Changes re-renders the grid).
    rolesAvailableToAdd() {
      const addedIds = new Set(this.extraRoles.map((role) => role.id));
      return this.addableRoles.filter((role) => !addedIds.has(role.id));
    },

    // Adds a client-side-only column for this view -- writes no SongRoleRequirement,
    // and is gone on reload or Cancel (ADR-0009's grid assigns people; #151 owns targets).
    addRole() {
      const roleId = Number(this.selectedRoleToAdd);
      const role = this.addableRoles.find((candidate) => candidate.id === roleId);
      if (!role) {
        return;
      }
      this.extraRoles.push(role);
      this.selectedRoleToAdd = '';
    },

    // Builds the "+" picker's fetch URL for an extra (client-only) column, whose
    // (song, role) pair the server never rendered a data-picker-url for.
    pickerUrlFor(songId, roleId) {
      return this.pickerUrlTemplate.replace(/\/0\/0\/$/, `/${songId}/${roleId}/`);
    },

    // Fetched only when a cell's "+" is opened -- an unopened cell issues no request. The dialog
    // isn't open yet while the fetch is in flight, so nothing stops a second "+" click from
    // starting a newer request before this one resolves; pickerRequestToken lets a stale response
    // recognize it's been superseded and bail rather than showing its (now mismatched) picker
    // markup against the newer click's cell ids.
    async openPicker(event) {
      const button = event.currentTarget;
      const requestToken = ++this.pickerRequestToken;
      this.pickerSongId = Number(button.dataset.songId);
      this.pickerRoleId = Number(button.dataset.roleId);
      this.pickerRehearsalSongId = button.dataset.rehearsalSongId ? Number(button.dataset.rehearsalSongId) : null;
      this.pickerError = '';
      this.pickerHtml = '';
      let response;
      try {
        response = await fetch(button.dataset.pickerUrl);
      } catch (error) {
        if (requestToken !== this.pickerRequestToken) {
          return;
        }
        this.pickerError = 'Could not reach the server to load the picker. Try again.';
        this.$refs.assignmentPickerDialog.showModal();
        return;
      }
      if (requestToken !== this.pickerRequestToken) {
        return;
      }
      if (!response.ok) {
        this.pickerError = 'Could not load the picker. Try again.';
        this.$refs.assignmentPickerDialog.showModal();
        return;
      }
      this.pickerHtml = await response.text();
      this.$refs.assignmentPickerDialog.showModal();
    },

    // Delegated click over the fetched picker markup: a standing-assignment row carries
    // data-picker-person-id/-name, a Backup row carries data-backup-picker-person-id/-name, so
    // any other click inside the dialog (e.g. the "Show all members" <summary>) is a no-op here.
    onPickerDialogClick(event) {
      const backupRow = event.target.closest('[data-backup-picker-person-id]');
      if (backupRow) {
        const personId = Number(backupRow.dataset.backupPickerPersonId);
        const personName = backupRow.dataset.backupPickerPersonName;
        const key = `${this.pickerRehearsalSongId}-${this.pickerRoleId}-${personId}`;
        if (!this.addedBackups.some((item) => item.key === key)) {
          const matchesPrefill = this.prefillBackup
            && this.prefillBackup.songId === this.pickerSongId
            && this.prefillBackup.roleId === this.pickerRoleId;
          this.addedBackups.push({
            key,
            rehearsalSongId: this.pickerRehearsalSongId,
            songId: this.pickerSongId,
            roleId: this.pickerRoleId,
            personId,
            personName,
            coveringForId: matchesPrefill ? this.prefillBackup.coveringForId : '',
          });
        }
        this.$refs.assignmentPickerDialog.close();
        return;
      }

      const personRow = event.target.closest('[data-picker-person-id]');
      if (!personRow) {
        return;
      }
      const personId = Number(personRow.dataset.pickerPersonId);
      const personName = personRow.dataset.pickerPersonName;
      const key = `${this.pickerSongId}-${this.pickerRoleId}-${personId}`;
      if (!this.added.some((item) => item.key === key)) {
        this.added.push({
          key, songId: this.pickerSongId, roleId: this.pickerRoleId, personId, personName,
        });
      }
      this.$refs.assignmentPickerDialog.close();
    },

    closePicker() {
      this.$refs.assignmentPickerDialog.close();
    },

    addedFor(songId, roleId) {
      return this.added.filter((item) => item.songId === songId && item.roleId === roleId);
    },

    removeAdded(key) {
      this.added = this.added.filter((item) => item.key !== key);
    },

    addedBackupsFor(songId, roleId) {
      return this.addedBackups.filter((item) => item.songId === songId && item.roleId === roleId);
    },

    removeAddedBackup(key) {
      this.addedBackups = this.addedBackups.filter((item) => item.key !== key);
    },

    // The cell's standing assignees, for a Backup's "covering for" select -- excludes the
    // Backup's own person, satisfying the self-cover check constraint client-side too.
    standingAssigneesFor(songId, roleId, excludePersonId) {
      const assignees = this.cellStandingAssignees[`${songId}-${roleId}`] || [];
      return assignees.filter((assignee) => assignee.id !== excludePersonId);
    },

    // A failed Preview (network error or non-2xx from the popover-close htmx request) must never read
    // as data loss: the Fallout region is left exactly as it was (htmx only swaps it on a successful
    // response), an inline note says so explicitly, and Save stays enabled -- Save recomputes and
    // revalidates everything server-side regardless (issue #212, mirroring issue #228's rosterEdit).
    onPreviewError() {
      this.previewError = 'Preview unavailable right now — your edits are still here, and Save is still enabled.';
    },

    onPreviewSettled() {
      this.previewError = '';
    },
  }));
});
