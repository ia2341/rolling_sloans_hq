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
  Alpine.data('assignmentGrid', (initialRemoved = [], initialAdded = [], initialEditing = false) => ({
    editing: initialEditing,
    removed: [...initialRemoved],
    added: [...initialAdded],
    removedBackups: [],
    addedBackups: [],
    pickerSongId: null,
    pickerRoleId: null,
    pickerRehearsalSongId: null,
    pickerHtml: '',
    pickerError: '',
    cellStandingAssignees: JSON.parse(document.getElementById('cell-standing-assignees-data').textContent),
    previewError: '',

    cancelEditing() {
      this.editing = false;
      this.removed = [];
      this.added = [];
      this.removedBackups = [];
      this.addedBackups = [];
    },

    // Fetched only when a cell's "+" is opened -- an unopened cell issues no request.
    async openPicker(event) {
      const button = event.currentTarget;
      this.pickerSongId = Number(button.dataset.songId);
      this.pickerRoleId = Number(button.dataset.roleId);
      this.pickerRehearsalSongId = button.dataset.rehearsalSongId ? Number(button.dataset.rehearsalSongId) : null;
      this.pickerError = '';
      this.pickerHtml = '';
      let response;
      try {
        response = await fetch(button.dataset.pickerUrl);
      } catch (error) {
        this.pickerError = 'Could not reach the server to load the picker. Try again.';
        this.$refs.assignmentPickerDialog.showModal();
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
          this.addedBackups.push({
            key,
            rehearsalSongId: this.pickerRehearsalSongId,
            songId: this.pickerSongId,
            roleId: this.pickerRoleId,
            personId,
            personName,
            coveringForId: '',
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
