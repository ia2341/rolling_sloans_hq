// The "Edit rehearsals" grid: repeatable "+ Add rehearsal", an undoable strike-through Rehearsal delete,
// the Running Order sub-grid's drag/keyboard reorder and its own undoable strike-through remove, a pending
// Dress flag's auto-collapse to a read-only ADR-0003 note, a debounced live Fallout fetch, and the one
// destructive-save confirmation dialog covering all three destructive causes together (issue #221) --
// this file's shape before this issue only covered the sub-grid (issue #220); it mirrors setlist_edit.js's
// and roster_edit.js's patterns throughout rather than inventing new ones. Registered once at page load
// (this file is loaded outside the htmx-swapped fragment), so Alpine's own mutation observer picks up and
// initializes the grid whether it arrives as a full page or an htmx swap.
document.addEventListener('alpine:init', () => {
  Alpine.data('scheduleEdit', (confirmUrl, previewUrl) => ({
    confirmHtml: '',
    confirmUrl,
    previewUrl,
    deleteError: '',
    sortables: [],
    falloutTimer: null,

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
      this.$el.querySelectorAll('.schedule-edit-row').forEach((row) => this.reindexRehearsalRow(row));
    },

    // Appends a brand-new Rehearsal row at the next never-before-used formset slot -- unlike drag/move
    // elsewhere in this grid, this is the one place a slot index gets assigned, and it happens exactly
    // once, at creation (mirrors setlist_edit.js's addRow()). Its end time is prefilled from the
    // Semester's default duration by the server (RehearsalEditRowForm's placeholder becomes the field's
    // own value here, since a brand-new row has nothing else to show).
    addRehearsalRow() {
      const template = document.getElementById('schedule-empty-row-template');
      const rows = document.getElementById('schedule-edit-rows');
      const totalForms = this.$el.querySelector('[name="rehearsal-TOTAL_FORMS"]');
      const nextIndex = Number(totalForms.value);
      const nextPrefix = `rehearsal-${nextIndex}`;
      const clone = template.content.cloneNode(true);
      clone.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace('__prefix__', String(nextIndex));
      });
      clone.querySelectorAll('[id]').forEach((element) => {
        element.id = element.id.replace('__prefix__', String(nextIndex));
      });
      clone.querySelectorAll('label[for]').forEach((label) => {
        label.setAttribute('for', label.getAttribute('for').replace('__prefix__', String(nextIndex)));
      });
      const rowEl = clone.querySelector('.schedule-edit-row');
      rowEl.dataset.formPrefix = nextPrefix;
      const subGrid = clone.querySelector('.running-order-sub-grid');
      subGrid.dataset.runningOrderFor = nextPrefix;
      clone.querySelector('.running-order-rows').id = `running-order-rows-${nextPrefix}`;
      rows.appendChild(clone);
      totalForms.value = String(nextIndex + 1);
      this.init();
      const dateInput = rowEl.querySelector('input[name$="-date"]');
      if (dateInput) {
        dateInput.focus();
      }
    },

    toggleRehearsalDelete(event) {
      const row = event.target.closest('.schedule-edit-row');
      const checkbox = row.querySelector('.schedule-edit-delete-checkbox-wrapper input');
      checkbox.checked = !checkbox.checked;
      this.reindexRehearsalRow(row);
    },

    reindexRehearsalRow(row) {
      const checkbox = row.querySelector('.schedule-edit-delete-checkbox-wrapper input');
      const deleted = checkbox.checked;
      row.classList.toggle('schedule-edit-row-deleted', deleted);
      const deleteButton = row.querySelector('.schedule-edit-delete-toggle');
      if (deleteButton) {
        deleteButton.textContent = deleted ? 'Undo' : 'Remove';
      }
    },

    // A pending Dress flag (issue #221) strikes every Running Order row this Rehearsal currently shows
    // and collapses the sub-grid to a read-only ADR-0003 note naming how many it removes -- un-checking
    // the flag only un-collapses the note; it never restores the struck rows (Un-flagging simply leaves
    // the rehearsal empty, per the spec -- reversing the toggle needs no ceremony beyond that).
    toggleDressCollapse(event) {
      const checkbox = event.target.closest('.schedule-edit-field-dress').querySelector('input[type=checkbox]');
      const row = event.target.closest('.schedule-edit-row');
      const subGrid = row.querySelector('.running-order-sub-grid');
      const note = row.querySelector('.running-order-dress-note');
      if (!checkbox.checked) {
        subGrid.hidden = false;
        note.style.display = 'none';
        return;
      }
      const rowsContainer = subGrid.querySelector('.running-order-rows');
      let removedCount = 0;
      Array.from(rowsContainer.querySelectorAll('.running-order-row')).forEach((songRow) => {
        const songCheckbox = songRow.querySelector('.running-order-delete-checkbox-wrapper input');
        if (!songCheckbox.checked) {
          songCheckbox.checked = true;
          removedCount += 1;
        }
      });
      this.reindex(rowsContainer);
      note.textContent = `Songs derive from the Setlist (ADR 0003) — this removes ${removedCount} scheduled song${removedCount === 1 ? '' : 's'}.`;
      note.style.display = '';
      subGrid.hidden = true;
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

    hasPendingDeletions() {
      const deletedRehearsal = Array.from(this.$el.querySelectorAll('.schedule-edit-delete-checkbox-wrapper input'))
        .some((checkbox) => checkbox.checked);
      const deletedRunningOrderRow = Array.from(this.$el.querySelectorAll('.running-order-delete-checkbox-wrapper input'))
        .some((checkbox) => checkbox.checked);
      return deletedRehearsal || deletedRunningOrderRow;
    },

    // Debounced live Fallout (issue #221, ADR 0008): fires on any change to the buffer, fetching the
    // exact same Preview call rendered into the #schedule-fallout region -- a Validation Error banner
    // and the two Fallout tiers, kept visually separate, never blocking a save.
    requestFallout() {
      clearTimeout(this.falloutTimer);
      this.falloutTimer = setTimeout(() => this.fetchFallout(), 400);
    },

    async fetchFallout() {
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData(form);
      let response;
      try {
        response = await fetch(this.previewUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body });
      } catch (error) {
        return;
      }
      if (!response.ok) {
        return;
      }
      document.getElementById('schedule-fallout').innerHTML = await response.text();
    },

    // Fetches the destructive-save confirmation (the same Preview call, rendered into a different
    // template per ADR 0008) and only opens the dialog on a successful response naming at least one
    // doomed Recording -- a failed request must never let 'Save Anyway' submit the destructive Save
    // without the admin having seen the counts, so it surfaces a retryable error instead. The dialog
    // fires once for the whole buffer, across all three destructive causes (mirrors setlist_edit.js
    // and roster_edit.js's own confirmation gates).
    async onSubmit(event) {
      if (!this.hasPendingDeletions()) {
        return;
      }
      event.preventDefault();
      this.deleteError = '';
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData(form);
      let response;
      try {
        response = await fetch(this.confirmUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body });
      } catch (error) {
        this.deleteError = 'Could not reach the server to confirm this Save. Check your connection and click Save Changes again.';
        return;
      }
      if (!response.ok) {
        this.deleteError = 'Could not load the Save confirmation. Click Save Changes again to retry.';
        return;
      }
      if (response.status === 204) {
        // No Recording is doomed after all -- the DOM's struck rows destroy nothing that has actual
        // audio, so the second (real) submit should proceed without a dialog the admin doesn't need.
        document.getElementById('schedule-edit-form').submit();
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
