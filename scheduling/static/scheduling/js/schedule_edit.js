// The "Edit rehearsals" grid: repeatable "+ Add rehearsal", an undoable strike-through Rehearsal delete,
// the Running Order sub-grid's drag/keyboard reorder and its own undoable strike-through remove, a pending
// Dress flag's auto-collapse to a read-only ADR-0003 note, a debounced live Fallout fetch, and the one
// destructive-save confirmation dialog covering all three destructive causes together (issue #221) --
// this file's shape before this issue only covered the sub-grid (issue #220); it mirrors setlist_edit.js's
// and roster_edit.js's patterns throughout rather than inventing new ones. Registered once at page load
// (this file is loaded outside the htmx-swapped fragment), so Alpine's own mutation observer picks up and
// initializes the grid whether it arrives as a full page or an htmx swap.
document.addEventListener('alpine:init', () => {
  Alpine.data('scheduleEdit', (confirmUrl, previewUrl, generateModalUrl, dealUrl, shuffleUrlTemplate) => ({
    confirmHtml: '',
    confirmUrl,
    previewUrl,
    generateModalUrl,
    dealUrl,
    shuffleUrlTemplate,
    dealError: '',
    deleteError: '',
    sortables: [],
    falloutTimer: null,
    falloutRequestId: 0,

    init() {
      // Bound via x-init on the component root (#schedule-edit-grid), so
      // `$el` and `$root` coincide here today -- but init() is also called
      // directly by addRehearsalRow() and afterApplyGeneration(), neither of
      // which runs inside a directive evaluation, so `$el` would be stale or
      // undefined there. Use `$root` so this method is correct regardless of
      // who calls it (issue #290).
      this.sortables.forEach((sortable) => sortable.destroy());
      this.sortables = [];
      this.$root.querySelectorAll('.running-order-rows').forEach((rows) => {
        this.sortables.push(Sortable.create(rows, {
          handle: '.running-order-drag-handle',
          animation: 150,
          onEnd: () => this.reindex(rows),
        }));
        this.reindex(rows);
        this.refreshAddSongOptions(rows);
      });
      this.$root.querySelectorAll('.schedule-edit-row').forEach((row) => this.reindexRehearsalRow(row));
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
      const rowEl = this._appendRehearsalRow();
      this.init();
      const dateInput = rowEl.querySelector('input[name$="-date"]');
      if (dateInput) {
        dateInput.focus();
      }
    },

    // Appends a brand-new Rehearsal row without focusing it -- the shared innards of addRehearsalRow()
    // (the toolbar's "+ Add rehearsal" click) and injectGeneratedCreate() (issue #222's staging modal's
    // Apply, which appends several rows in a row and must not steal focus for each one).
    _appendRehearsalRow() {
      // Reached from addRehearsalRow() (bound on the "+ Add rehearsal"
      // button) and injectGeneratedCreate() (called directly on this
      // component's data from rehearsal_generation.js's applyGeneration(),
      // outside any directive evaluation) -- `$el` is wrong in both cases,
      // so this must resolve the formset via `$root` (issue #290).
      const template = document.getElementById('schedule-empty-row-template');
      const rows = document.getElementById('schedule-edit-rows');
      const totalForms = this.$root.querySelector('[name="rehearsal-TOTAL_FORMS"]');
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
      return document.getElementById('schedule-edit-rows').lastElementChild;
    },

    // Fetches the "Generate rehearsal dates" staging modal (issue #222) into its container the first time
    // it's opened, then shows it -- a subsequent open reuses the same fetched dialog rather than
    // re-fetching, so a Preview an admin already ran survives closing and reopening the modal by accident.
    async openGenerateModal() {
      const container = document.getElementById('generate-modal-container');
      if (!container.querySelector('dialog')) {
        const response = await fetch(this.generateModalUrl);
        if (!response.ok) {
          return;
        }
        container.innerHTML = await response.text();
      }
      container.querySelector('dialog').showModal();
    },

    // Returns true when `row`'s date/start/end no longer match what the page loaded with -- an admin's
    // own hand-edit of a Rehearsal the generation diff also wants to touch. Read from the row's own
    // data-original-* attributes rather than a second fetch, since the Buffer this compares against is
    // exactly what's on-screen right now (issue #222).
    _isRowDirty(row) {
      const dateInput = row.querySelector('input[name$="-date"]');
      const startInput = row.querySelector('input[name$="-start_time"]');
      const endInput = row.querySelector('input[name$="-end_time"]');
      return (
        dateInput.value !== row.dataset.originalDate
        || startInput.value !== row.dataset.originalStartTime
        || endInput.value !== row.dataset.originalEndTime
      );
    },

    // Appends a brand-new Rehearsal row prefilled from one ticked Create outcome (issue #222's staging
    // modal Apply) -- date/start/end/Dress land straight on the freshly-appended row's own inputs, which
    // mirrors exactly what a hand-typed "+ Add rehearsal" row would carry into the Pending Buffer.
    // Reconciles onto an already-pending row for the same date instead of appending a second one: Preview
    // only sees saved Rehearsals, so a date an admin already hand-added to the Buffer looks like a Create
    // to it too, and the schedule formset itself rejects two rows sharing a date (issue #222 review).
    injectGeneratedCreate({ date, startTime, endTime, isDressRehearsal }) {
      const rowEl = this._findPendingRowByDate(date) || this._appendRehearsalRow();
      rowEl.querySelector('input[name$="-date"]').value = date;
      rowEl.querySelector('input[name$="-start_time"]').value = startTime;
      rowEl.querySelector('input[name$="-end_time"]').value = endTime;
      if (isDressRehearsal) {
        rowEl.querySelector('input[name$="-is_full_setlist"]').checked = true;
      }
    },

    // Finds a grid row -- saved or freshly hand-added -- not marked for deletion whose date input already
    // matches `date`, so injectGeneratedCreate() can reconcile onto it rather than duplicate it.
    _findPendingRowByDate(date) {
      return Array.from(document.querySelectorAll('.schedule-edit-row')).find((row) => {
        const dateInput = row.querySelector('input[name$="-date"]');
        const deleteCheckbox = row.querySelector('.schedule-edit-delete-checkbox-wrapper input');
        return dateInput.value === date && !(deleteCheckbox && deleteCheckbox.checked);
      });
    },

    // Re-times an existing Rehearsal row already on the grid to a ticked outcome's new hours (issue #222)
    // -- refuses (returning false) when the admin already hand-edited this exact row, so Apply can never
    // silently clobber an in-progress edit; the caller reports that refusal, this method only detects it.
    injectGeneratedRetime({ rehearsalId, startTime, endTime }) {
      const row = document.getElementById(`schedule-edit-row-${rehearsalId}`);
      if (!row || this._isRowDirty(row)) {
        return false;
      }
      row.querySelector('input[name$="-start_time"]').value = startTime;
      row.querySelector('input[name$="-end_time"]').value = endTime;
      return true;
    },

    // Marks an existing Rehearsal row's Remove checkbox for a ticked Orphan-delete outcome (issue #222)
    // -- refuses (returning false) the same way injectGeneratedRetime() does, for the same reason.
    injectGeneratedOrphanDelete({ rehearsalId }) {
      const row = document.getElementById(`schedule-edit-row-${rehearsalId}`);
      if (!row || this._isRowDirty(row)) {
        return false;
      }
      const checkbox = row.querySelector('.schedule-edit-delete-checkbox-wrapper input');
      checkbox.checked = true;
      this.reindexRehearsalRow(row);
      return true;
    },

    // Runs after rehearsal_generation.js's Apply has injected every ticked outcome -- re-wires SortableJS
    // and re-derives visible numbering on the rows Apply appended, and refreshes the live Fallout the
    // same as any other buffer change would.
    afterApplyGeneration() {
      this.init();
      this.requestFallout();
    },

    // "Generate schedule" and "Re-roll" (issue #223): both call this exact same endpoint -- a fresh POST is a
    // fresh random deal, and nothing about a deal is ever persisted between runs, so a "re-roll" needs no
    // endpoint of its own. Fills every eligible Rehearsal's Running Order sub-grid (including one nobody has
    // expanded) straight from the server's proposed deal; a refusal (empty setlist, no eligible Rehearsal)
    // renders its reason in #schedule-deal-error rather than touching the buffer at all.
    async dealSchedule() {
      this.dealError = '';
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      let response;
      try {
        response = await fetch(this.dealUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
      } catch (error) {
        this.dealError = 'Could not reach the server to generate a schedule. Check your connection and try again.';
        return;
      }
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        this.dealError = (body && body.error) || 'Could not generate a schedule. Try again.';
        return;
      }
      const body = await response.json();
      body.rehearsals.forEach(({ rehearsal_id: rehearsalId, rows }) => {
        const row = document.querySelector(`.schedule-edit-row[data-rehearsal-id="${rehearsalId}"]`);
        if (!row) {
          return;
        }
        this._applyRowsToSubGrid(row.querySelector('.running-order-sub-grid'), rows, { supersedeExisting: true });
        row.querySelector('.running-order-expander').open = true;
      });
      this.requestFallout();
    },

    // Per-Rehearsal Shuffle (issue #223): reorders that one Rehearsal's own already-saved Running Order --
    // never adds, removes or redeals a Song, so term-wide ±1 balance is preserved by construction. Only
    // rendered for an already-saved Rehearsal (see _schedule_edit_row.html): a brand-new row has no saved
    // Running Order yet for shuffle_rehearsal_running_order() to read.
    async shuffleRehearsal(event) {
      const row = event.target.closest('.schedule-edit-row');
      const rehearsalId = row.dataset.rehearsalId;
      if (!rehearsalId) {
        return;
      }
      const form = document.getElementById('schedule-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const url = this.shuffleUrlTemplate.replace('/0/shuffle/', `/${rehearsalId}/shuffle/`);
      let response;
      try {
        response = await fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
      } catch (error) {
        return;
      }
      if (!response.ok) {
        return;
      }
      const body = await response.json();
      if (!body.rows.length) {
        return;
      }
      this._applyRowsToSubGrid(row.querySelector('.running-order-sub-grid'), body.rows, { supersedeExisting: false });
      this.requestFallout();
    },

    // Shared innards of dealSchedule() and shuffleRehearsal() (issue #223): walks `targetRows` (each either an
    // existing RehearsalSong's identity to reuse, or a brand-new Song to deal in) in its exact target order,
    // moving/inserting each row's element into that sequence -- physical DOM order is what song_slot_order's
    // sequence saves as the final Running Order, so this is the one place that order is actually produced.
    // `supersedeExisting` (true only for a deal, never a shuffle) marks every currently-present row this
    // target list does NOT keep as a pending removal first, mirroring the grid's other undoable strike-through
    // deletes -- a shuffle never marks anything, since every row it's handed is already exactly the set on
    // screen, just reordered.
    //
    // A `data-pinned="true"` row (recording-bearing or hand-raised slot_count -- see _running_order_row.html)
    // is never physically moved here, even though the server's returned position for it matches where it
    // already sits in the saved Running Order: an admin can have dragged it somewhere else in the *unsaved*
    // Pending Buffer before clicking Deal/Shuffle, and physically relocating it on the server's say-so would
    // silently discard that unsaved move. It's still used as the anchor the surrounding free rows are inserted
    // around, so the rest of the sequence still lands correctly -- only the pinned row itself stays put.
    _applyRowsToSubGrid(subGrid, targetRows, { supersedeExisting }) {
      const rowsContainer = subGrid.querySelector('.running-order-rows');
      if (supersedeExisting) {
        const keptIds = new Set(targetRows.map((row) => row.rehearsal_song_id).filter((id) => id !== null));
        Array.from(rowsContainer.querySelectorAll('.running-order-row')).forEach((rowEl) => {
          const rehearsalSongId = rowEl.dataset.rehearsalSongId ? Number(rowEl.dataset.rehearsalSongId) : null;
          if (rehearsalSongId !== null && keptIds.has(rehearsalSongId)) {
            return;
          }
          const checkbox = rowEl.querySelector('.running-order-delete-checkbox-wrapper input');
          if (!checkbox.checked) {
            checkbox.checked = true;
            rowEl.classList.remove('running-order-row-dress-struck');
          }
        });
      }
      let insertionPoint = null;
      targetRows.forEach((target) => {
        const rowEl = target.rehearsal_song_id !== null
          ? rowsContainer.querySelector(`.running-order-row[data-rehearsal-song-id="${target.rehearsal_song_id}"]`)
          : this._createRunningOrderRow(subGrid, target.song_id, target.slot_count);
        if (!rowEl) {
          return;
        }
        if (rowEl.dataset.pinned !== 'true') {
          if (insertionPoint) {
            insertionPoint.after(rowEl);
          } else {
            rowsContainer.prepend(rowEl);
          }
        }
        insertionPoint = rowEl;
      });
      this.reindex(rowsContainer);
      this.refreshAddSongOptions(rowsContainer);
    },

    // Builds one brand-new (detached) Running Order row for a dealt Song at `slotCount` -- the same
    // <template>-clone-and-reindex shape as addRunningOrderSong(), generalized to take its Song/slot_count as
    // arguments instead of reading them off a picker <select> event (issue #223).
    _createRunningOrderRow(subGrid, songId, slotCount) {
      const rehearsalKey = subGrid.dataset.runningOrderFor;
      const select = subGrid.querySelector('.running-order-add-song-select');
      const option = select
        ? Array.from(select.options).find((candidate) => candidate.value === String(songId))
        : null;
      const template = document.getElementById('running-order-empty-form-template');
      // Reached from dealSchedule()/shuffleRehearsal() (both button-bound,
      // then several stack frames removed from the click) via
      // _applyRowsToSubGrid() -- `$el` there is the button, not the
      // formset's own root, so this must use `$root` (issue #290).
      const totalForms = this.$root.querySelector('[name="songs-TOTAL_FORMS"]');
      const nextIndex = Number(totalForms.value);
      const clone = template.content.cloneNode(true);
      clone.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace('__prefix__', String(nextIndex));
      });
      const row = clone.querySelector('.running-order-row');
      row.dataset.songId = String(songId);
      row.dataset.formPrefix = `songs-${nextIndex}`;
      row.querySelector('input[name$="-rehearsal_row_key"]').value = rehearsalKey;
      row.querySelector('input[name$="-song_id"]').value = songId;
      row.querySelector('.running-order-order-field').value = `songs-${nextIndex}`;
      const slotInput = row.querySelector('input[name$="-slot_count"]');
      if (slotInput) {
        slotInput.value = slotCount;
      }
      row.querySelector('.running-order-song-title').textContent = option ? (option.dataset.title || option.textContent) : '';
      totalForms.value = String(nextIndex + 1);
      return row;
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
      // Bound directly on the "+ Add song" <select> (@change="addRunningOrderSong($event)"),
      // so `$el` here is a `<select>` inside one Rehearsal's sub-grid, not the
      // component root -- use `$root` (issue #290).
      const totalForms = this.$root.querySelector('[name="songs-TOTAL_FORMS"]');
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
      // Reached from onSubmit, where `$el` is the `<form>` -- it happens to
      // contain every row searched below today, but that's a coincidence of
      // markup nesting, not a guarantee. Use `$root` (issue #290).
      const deletedRehearsal = Array.from(this.$root.querySelectorAll('.schedule-edit-delete-checkbox-wrapper input'))
        .some((checkbox) => checkbox.checked);
      const deletedRunningOrderRow = Array.from(this.$root.querySelectorAll('.running-order-delete-checkbox-wrapper input'))
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
