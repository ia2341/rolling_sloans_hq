// The assignment grid's edit-mode buffer (issue #210) plus the per-cell "+" popover picker
// (issue #211). Both the ✕ removal buffer and the picker's picks live in this one Alpine
// component so "Save Changes" commits both kinds of buffered change together.
//
// The picker's fetched HTML is injected via x-html, which Alpine never re-scans for
// directives, so its person rows carry no @click of their own -- clicking one is caught by
// event delegation on the static <dialog> wrapper instead (a plain DOM click bubbles through
// injected content exactly like any other node).
document.addEventListener('alpine:init', () => {
  Alpine.data('assignmentGrid', () => ({
    editing: false,
    removed: [],
    added: [],
    pickerSongId: null,
    pickerRoleId: null,
    pickerHtml: '',
    pickerError: '',

    cancelEditing() {
      this.editing = false;
      this.removed = [];
      this.added = [];
    },

    // Fetched only when a cell's "+" is opened -- an unopened cell issues no request.
    async openPicker(event) {
      const button = event.currentTarget;
      this.pickerSongId = Number(button.dataset.songId);
      this.pickerRoleId = Number(button.dataset.roleId);
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

    // Delegated click over the fetched picker markup: a person row carries
    // data-picker-person-id/-name, so any other click inside the dialog (e.g. the
    // "Show all members" <summary>) is a no-op here.
    onPickerDialogClick(event) {
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
  }));
});
