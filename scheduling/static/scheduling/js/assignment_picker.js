// The assignment grid's edit-mode buffer (issue #210) plus the per-cell "+" popover picker
// (issue #211). Both the ✕ removal buffer and the picker's picks live in this one Alpine
// component so "Save Changes" commits both kinds of buffered change together.
//
// The picker's fetched HTML is injected via x-html, which Alpine never re-scans for
// directives, so its person rows carry no @click of their own -- clicking one is caught by
// event delegation on the static <dialog> wrapper instead (a plain DOM click bubbles through
// injected content exactly like any other node).
document.addEventListener('alpine:init', () => {
  Alpine.data('assignmentGrid', (pickerUrlTemplate) => ({
    editing: false,
    removed: [],
    added: [],
    pickerSongId: null,
    pickerRoleId: null,
    pickerHtml: '',
    pickerError: '',
    pickerUrlTemplate: pickerUrlTemplate || '',
    extraRoles: [],
    selectedRoleToAdd: '',
    addableRoles: [],

    // "+ Add role" (issue #213): every addable Role (active, not already a column),
    // read once from the json_script the server rendered -- a plain data island, not
    // an Alpine.data() init arg, since a Role name could contain a quote or apostrophe.
    init() {
      const dataEl = document.getElementById('addable-roles-data');
      this.addableRoles = dataEl ? JSON.parse(dataEl.textContent) : [];
    },

    cancelEditing() {
      this.editing = false;
      this.removed = [];
      this.added = [];
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
