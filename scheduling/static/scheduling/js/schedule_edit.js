// The "Edit rehearsals" grid's Running Order sub-grid: drag/keyboard reorder (confined to one Rehearsal),
// a "+ Add song" picker excluding already-scheduled songs, and an undoable strike-through remove with a
// Recordings confirmation dialog (issue #220) -- the first consumer of the vendored SortableJS unless #179
// already claimed that spot, in which case this mirrors setlist_edit.js's shape rather than a second approach.
// Registered once at page load (this file is loaded outside the htmx-swapped fragment), so Alpine's own
// mutation observer picks up and initializes the grid whether it arrives as a full page or an htmx swap.
document.addEventListener('alpine:init', () => {
  Alpine.data('scheduleEdit', (confirmUrl) => ({
    confirmHtml: '',
    confirmUrl,
    deleteError: '',
    sortables: [],

    init() {
      this.sortables.forEach((sortable) => sortable.destroy());
      this.sortables = [];
      this.$el.querySelectorAll('.running-order-rows').forEach((rows) => {
        this.sortables.push(Sortable.create(rows, {
          handle: '.running-order-drag-handle',
          animation: 150,
          onEnd: () => this.reindex(rows),
        }));
        this.reindex(rows);
        this.refreshAddSongOptions(rows);
      });
    },

    // Appends a brand-new Running Order row at the next never-before-used formset slot, into the
    // Rehearsal sub-grid the picker lives in -- unlike drag/move, this is the one place a slot index
    // gets assigned, and it happens exactly once, at creation (mirrors setlist_edit.js's addRow()).
    addRunningOrderSong(event) {
      const select = event.target;
      const songId = select.value;
      if (!songId) {
        return;
      }
      const option = select.selectedOptions[0];
      const subGrid = select.closest('.running-order-sub-grid');
      const rehearsalKey = subGrid.dataset.runningOrderFor;
      const rows = subGrid.querySelector('.running-order-rows');
      const template = document.getElementById('running-order-empty-form-template');
      const totalForms = this.$el.querySelector('[name="songs-TOTAL_FORMS"]');
      const nextIndex = Number(totalForms.value);
      const clone = template.content.cloneNode(true);
      clone.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace('__prefix__', String(nextIndex));
      });
      const row = clone.querySelector('.running-order-row');
      row.dataset.songId = songId;
      row.dataset.formPrefix = `songs-${nextIndex}`;
      row.querySelector('input[name$="-rehearsal_row_key"]').value = rehearsalKey;
      row.querySelector('input[name$="-song_id"]').value = songId;
      row.querySelector('.running-order-order-field').value = `songs-${nextIndex}`;
      row.querySelector('.running-order-song-title').textContent = option.dataset.title || option.textContent;
      rows.appendChild(clone);
      totalForms.value = String(nextIndex + 1);
      select.value = '';
      this.reindex(rows);
      this.refreshAddSongOptions(rows);
    },

    moveUp(event) {
      const row = event.target.closest('.running-order-row');
      const previous = row.previousElementSibling;
      if (previous) {
        row.parentElement.insertBefore(row, previous);
        this.reindex(row.parentElement);
      }
    },

    moveDown(event) {
      const row = event.target.closest('.running-order-row');
      const next = row.nextElementSibling;
      if (next) {
        row.parentElement.insertBefore(next, row);
        this.reindex(row.parentElement);
      }
    },

    toggleRunningOrderDelete(event) {
      const row = event.target.closest('.running-order-row');
      const checkbox = row.querySelector('.running-order-delete-checkbox-wrapper input');
      checkbox.checked = !checkbox.checked;
      this.reindex(row.parentElement);
      this.refreshAddSongOptions(row.parentElement);
    },

    // Recomputes one Rehearsal's Running Order '#' column from its own rows container's current DOM
    // order -- a row's formset slot (songs-N-*) never changes here, only which visible number it shows
    // and whether it reads as struck (mirrors setlist_edit.js's reindex()).
    reindex(rows) {
      const rowEls = Array.from(rows.children);
      let visibleNumber = 0;
      rowEls.forEach((row) => {
        const checkbox = row.querySelector('.running-order-delete-checkbox-wrapper input');
        const deleted = checkbox.checked;
        row.classList.toggle('running-order-row-deleted', deleted);
        const numberCell = row.querySelector('.running-order-row-number');
        if (deleted) {
          numberCell.textContent = '—';
        } else {
          visibleNumber += 1;
          numberCell.textContent = String(visibleNumber);
        }
        const deleteButton = row.querySelector('.running-order-delete-toggle');
        if (deleteButton) {
          deleteButton.textContent = deleted ? 'Undo' : 'Remove';
        }
      });
    },

    // Hides a Rehearsal's "+ Add song" options for any Song already present in its own rows container --
    // a row still on-screen counts even if struck for removal, since it is only actually gone once Save
    // Changes commits (issue #220's "excluding songs already scheduled in that rehearsal").
    refreshAddSongOptions(rows) {
      const subGrid = rows.closest('.running-order-sub-grid');
      const select = subGrid.querySelector('.running-order-add-song-select');
      if (!select) {
        return;
      }
      const presentSongIds = new Set(
        Array.from(rows.querySelectorAll('.running-order-row')).map((row) => row.dataset.songId),
      );
      Array.from(select.options).forEach((option) => {
        if (option.value) {
          option.hidden = presentSongIds.has(option.value);
        }
      });
    },

    deletedRehearsalSongIds() {
      return Array.from(this.$el.querySelectorAll('.running-order-row'))
        .filter((row) => row.dataset.rehearsalSongId && row.querySelector('.running-order-delete-checkbox-wrapper input').checked)
        .map((row) => row.dataset.rehearsalSongId);
    },

    // Fetches the deletion confirmation and only opens the dialog on a successful response -- a failed
    // request must never let 'Remove Anyway' submit the destructive Save without the admin having seen
    // the recording/uploader counts, so it surfaces a retryable error instead (mirrors setlist_edit.js).
    async onSubmit(event) {
      const rehearsalSongIds = this.deletedRehearsalSongIds();
      if (rehearsalSongIds.length === 0) {
        return;
      }
      event.preventDefault();
      this.deleteError = '';
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData();
      rehearsalSongIds.forEach((id) => body.append('rehearsal_song_id', id));
      let response;
      try {
        response = await fetch(this.confirmUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
          body,
        });
      } catch (error) {
        this.deleteError = 'Could not reach the server to confirm removals. Check your connection and click Save Changes again.';
        return;
      }
      if (!response.ok) {
        this.deleteError = 'Could not load the removal confirmation. Click Save Changes again to retry.';
        return;
      }
      this.confirmHtml = await response.text();
      this.$refs.deleteDialog.showModal();
    },

    confirmDelete() {
      this.$refs.deleteDialog.close();
      // .submit() (unlike .requestSubmit()) fires no 'submit' event, so this bypasses onSubmit's
      // confirmation gate on the second pass -- the admin already saw and accepted the counts.
      document.getElementById('schedule-edit-form').submit();
    },

    cancelDelete() {
      this.$refs.deleteDialog.close();
    },
  }));
});
