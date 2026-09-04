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
    falloutRequestId: 0,

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
      this.openTargetedRunningOrder();
    },

    // Opens and scrolls to a #schedule-edit-row-<id> Rehearsal's Running Order sub-grid on arrival
    // (issue #195's door from the adjudication table) -- a no-op for a plain visit with no hash.
    openTargetedRunningOrder() {
      if (!window.location.hash) {
        return;
      }
      const target = document.querySelector(window.location.hash);
      if (!target) {
        return;
      }
      const expander = target.querySelector('.running-order-expander');
      if (expander) {
        expander.open = true;
      }
      target.scrollIntoView();
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
      this.requestFallout();
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
    // the flag restores only the rows this same toggle struck (tagged `running-order-row-dress-struck`),
    // leaving any row the admin had already, separately struck by hand exactly as they left it.
    toggleDressCollapse(event) {
      const checkbox = event.target.closest('.schedule-edit-field-dress').querySelector('input[type=checkbox]');
      const row = event.target.closest('.schedule-edit-row');
      const subGrid = row.querySelector('.running-order-sub-grid');
      const note = row.querySelector('.running-order-dress-note');
      const rowsContainer = subGrid.querySelector('.running-order-rows');
      if (!checkbox.checked) {
        Array.from(rowsContainer.querySelectorAll('.running-order-row.running-order-row-dress-struck')).forEach((songRow) => {
          songRow.classList.remove('running-order-row-dress-struck');
          songRow.querySelector('.running-order-delete-checkbox-wrapper input').checked = false;
        });
        this.reindex(rowsContainer);
        subGrid.hidden = false;
        note.style.display = 'none';
        this.requestFallout();
        return;
      }
      let removedCount = 0;
      Array.from(rowsContainer.querySelectorAll('.running-order-row')).forEach((songRow) => {
        const songCheckbox = songRow.querySelector('.running-order-delete-checkbox-wrapper input');
        if (!songCheckbox.checked) {
          songCheckbox.checked = true;
          songRow.classList.add('running-order-row-dress-struck');
          removedCount += 1;
        }
      });
      this.reindex(rowsContainer);
      note.textContent = `Songs derive from the Setlist (ADR 0003) — this removes ${removedCount} scheduled song${removedCount === 1 ? '' : 's'}.`;
      note.style.display = '';
      subGrid.hidden = true;
      this.requestFallout();
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
      row.classList.remove('running-order-row-dress-struck');
      this.reindex(row.parentElement);
      this.refreshAddSongOptions(row.parentElement);
      this.requestFallout();
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

    // Guards against an older request's response overwriting a newer one -- fetches race under a 400ms
    // debounce whenever the network is slow, so only the response matching the latest requestId that was
    // still current when it started may render (a superseded request's response is simply dropped).
    async fetchFallout() {
      const requestId = ++this.falloutRequestId;
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
      const html = await response.text();
      if (requestId !== this.falloutRequestId) {
        return;
      }
      document.getElementById('schedule-fallout').innerHTML = html;
    },

    // Disables (or re-enables) every field in the form -- used to freeze the buffer for the span between
    // requesting the destructive-save confirmation and the admin acting on it, so the payload the real
    // Save submits can never drift from the one the confirmation's counts were computed against. A
    // disabled field is excluded from FormData/a native submit, so callers must always re-enable
    // synchronously, in the same tick as the submit that follows, never leaving an await in between.
    setFormFieldsDisabled(disabled) {
      document.getElementById('schedule-edit-form').querySelectorAll('input, select, textarea, button')
        .forEach((field) => { field.disabled = disabled; });
    },

    // Fetches the destructive-save confirmation (the same Preview call, rendered into a different
    // template per ADR 0008) and only opens the dialog on a successful response naming at least one
    // doomed Recording -- a failed request must never let 'Save Anyway' submit the destructive Save
    // without the admin having seen the counts, so it surfaces a retryable error instead. The dialog
    // fires once for the whole buffer, across all three destructive causes (mirrors setlist_edit.js
    // and roster_edit.js's own confirmation gates). The form is frozen for the whole span from here
    // until the admin cancels or confirms, so a slow response's counts can never go stale against a
    // buffer the admin kept editing underneath it.
    async onSubmit(event) {
      if (!this.hasPendingDeletions()) {
        return;
      }
      event.preventDefault();
      this.deleteError = '';
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData(form);
      this.setFormFieldsDisabled(true);
      let response;
      try {
        response = await fetch(this.confirmUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body });
      } catch (error) {
        this.setFormFieldsDisabled(false);
        this.deleteError = 'Could not reach the server to confirm this Save. Check your connection and click Save Changes again.';
        return;
      }
      if (!response.ok) {
        this.setFormFieldsDisabled(false);
        this.deleteError = 'Could not load the Save confirmation. Click Save Changes again to retry.';
        return;
      }
      if (response.status === 204) {
        // No Recording is doomed after all -- the DOM's struck rows destroy nothing that has actual
        // audio, so the second (real) submit should proceed without a dialog the admin doesn't need.
        this.setFormFieldsDisabled(false);
        document.getElementById('schedule-edit-form').submit();
        return;
      }
      this.confirmHtml = await response.text();
      this.$refs.deleteDialog.showModal();
    },

    confirmDelete() {
      this.$refs.deleteDialog.close();
      // Re-enabling and submitting in the same synchronous call leaves no gap for the admin to touch
      // the (visibly frozen) form in between -- .submit() (unlike .requestSubmit()) also fires no
      // 'submit' event, so this bypasses onSubmit's confirmation gate on the second pass.
      this.setFormFieldsDisabled(false);
      document.getElementById('schedule-edit-form').submit();
    },

    cancelDelete() {
      this.$refs.deleteDialog.close();
      this.setFormFieldsDisabled(false);
    },
  }));
});
