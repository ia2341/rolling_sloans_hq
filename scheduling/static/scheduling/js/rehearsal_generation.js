// The "Generate rehearsal dates" staging modal (issue #222): a repeatable Rehearsal Time / Skip Date
// editor, a "Preview" action that first saves the Pattern (so it's remembered between runs) then renders
// the four-bucket diff, and an Apply that injects ticked outcomes into the page's existing Pending Buffer
// (schedule_edit.js's scheduleEdit component) without ever writing a Rehearsal itself. Mirrors
// schedule_edit.js's and setlist_edit.js's patterns throughout: a plain <template>-clone "+ Add" per
// repeatable list, a debounce-free fetch pair for Preview, no client-side reimplementation of the diff
// (the server computes it every time, per ADR 0008's spirit even though this surface has no apply_*() to
// roll back).
document.addEventListener('alpine:init', () => {
  Alpine.data('rehearsalGeneration', (saveUrl, previewUrl, defaultDurationMinutes) => ({
    saveUrl,
    previewUrl,
    defaultDurationMinutes,
    diffHtml: '',
    previewError: '',
    isPreviewing: false,

    init() {},

    // The native <dialog> 'close' event (Close button, Esc, or backdrop dismissal) fires this -- it only
    // clears the rendered diff, since a stale diff could otherwise appear to describe a Pattern the admin
    // has since changed. The Pattern editor's own field values are left exactly as they are: reopening
    // the modal re-fetches from the server anyway (schedule_edit.js's openGenerateModal() only fetches
    // once), so nothing here needs to reset them for that case, and closing the modal must write nothing.
    reset() {
      this.diffHtml = '';
      this.previewError = '';
    },

    close() {
      this.$el.close();
    },

    addRehearsalTimeRow() {
      this._appendRow('rehearsal-time-empty-row-template', 'rehearsal-time-rows-list', 'rehearsal-time');
      const rows = document.getElementById('rehearsal-time-rows-list');
      const rowEl = rows.lastElementChild;
      const startInput = rowEl.querySelector('input[name$="-start_time"]');
      const endInput = rowEl.querySelector('input[name$="-end_time"]');
      // A new Rehearsal Time's end is prefilled from the Semester's default duration (issue #222), derived
      // from whatever start time gets typed -- there's nothing to derive from until then.
      startInput.addEventListener('change', () => {
        if (!endInput.value && startInput.value) {
          endInput.value = this._addMinutes(startInput.value, this.defaultDurationMinutes);
        }
      }, { once: true });
    },

    removeRehearsalTimeRow(event) {
      this._markRowRemoved(event.target.closest('.rehearsal-time-row'), '.rehearsal-time-delete-checkbox-wrapper');
    },

    addSkipDateRow() {
      this._appendRow('skip-date-empty-row-template', 'skip-date-rows-list', 'skip-date');
    },

    removeSkipDateRow(event) {
      this._markRowRemoved(event.target.closest('.skip-date-row'), '.skip-date-delete-checkbox-wrapper');
    },

    // Shared "+ Add" innards for both repeatable lists -- clones a <template>, does __prefix__ -> next
    // index substitution on name/id/label[for], and bumps that formset's own TOTAL_FORMS (mirrors
    // schedule_edit.js's addRehearsalRow()/_appendRehearsalRow()).
    _appendRow(templateId, rowsId, formsetPrefix) {
      const template = document.getElementById(templateId);
      const rows = document.getElementById(rowsId);
      const totalForms = this.$el.querySelector(`[name="${formsetPrefix}-TOTAL_FORMS"]`);
      const nextIndex = Number(totalForms.value);
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
      rows.appendChild(clone);
      totalForms.value = String(nextIndex + 1);
    },

    // An undoable "Remove" would need a struck-row affordance this modal has no room for -- a Pattern row
    // is input history with no other referent, so removing one here is a plain hide-and-mark-deleted, not
    // the strike-through/Undo pattern the Rehearsal grid itself uses for real, saved rows.
    _markRowRemoved(row, checkboxWrapperSelector) {
      row.querySelector(`${checkboxWrapperSelector} input`).checked = true;
      row.style.display = 'none';
    },

    _addMinutes(hhmm, minutes) {
      const [hours, mins] = hhmm.split(':').map(Number);
      const total = ((hours * 60) + mins + minutes) % (24 * 60);
      const outHours = Math.floor(total / 60);
      const outMinutes = total % 60;
      return `${String(outHours).padStart(2, '0')}:${String(outMinutes).padStart(2, '0')}`;
    },

    _formData() {
      return new FormData(document.getElementById('rehearsal-pattern-form'));
    },

    _csrfToken() {
      return document.getElementById('rehearsal-pattern-form').querySelector('[name=csrfmiddlewaretoken]').value;
    },

    // Saves the Pattern first (so it's remembered between runs, per CONTEXT.md), then -- only if that
    // succeeds -- renders the four-bucket diff for the exact same submitted state. The two are separate
    // requests to separate endpoints, mirroring the service layer's own deliberate split between
    // save_rehearsal_pattern() and the pure-read preview_rehearsal_generation() (issue #222).
    async runPreview() {
      if (this.isPreviewing) {
        // The Preview button is :disabled while a run is in flight, but a guard here too costs
        // nothing and covers any trigger other than a click (e.g. a stray Enter-key submit).
        return;
      }
      this.isPreviewing = true;
      this.previewError = '';
      this.diffHtml = '';
      const csrfToken = this._csrfToken();
      // Captured once and reused for both requests: the Preview diff must describe the exact
      // same submitted state that got saved, not whatever the form happens to hold by the time
      // the second request goes out (issue #222 review).
      const formData = this._formData();
      try {
        let saveResponse;
        try {
          saveResponse = await fetch(this.saveUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: formData });
        } catch (error) {
          this.previewError = 'Could not reach the server to save this Pattern. Check your connection and try again.';
          return;
        }
        if (!saveResponse.ok) {
          this.previewError = 'Could not save this Pattern. Try again.';
          return;
        }
        const savedEditorHtml = await saveResponse.text();
        document.getElementById('rehearsal-pattern-body').innerHTML = savedEditorHtml;
        if (document.getElementById('rehearsal-pattern-save-error')) {
          // The editor re-render already carries the field-level/collision error; nothing further to fetch.
          return;
        }

        let previewResponse;
        try {
          previewResponse = await fetch(this.previewUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: formData });
        } catch (error) {
          this.previewError = 'Could not reach the server to compute this diff. Check your connection and try again.';
          return;
        }
        if (!previewResponse.ok) {
          this.previewError = 'Could not compute this diff. Try again.';
          return;
        }
        this.diffHtml = await previewResponse.text();
      } finally {
        this.isPreviewing = false;
      }
    },

    // Reads every ticked outcome straight off the rendered diff's own DOM (data-* attributes set by
    // _rehearsal_generation_diff.html) and hands each to the parent page's scheduleEdit component, which
    // owns the actual Pending Buffer -- this component never touches #schedule-edit-grid's formsets
    // directly. A re-time or orphan-delete whose row is already dirty in the Buffer is refused rather
    // than clobbered (issue #222); refusals are collected and reported once, not popped up per-row.
    applyGeneration() {
      const scheduleEdit = Alpine.$data(document.getElementById('schedule-edit-grid'));
      const region = document.getElementById('rehearsal-generation-diff-region');
      const refused = [];

      region.querySelectorAll('.rs-generation-create-checkbox:checked').forEach((checkbox) => {
        scheduleEdit.injectGeneratedCreate({
          date: checkbox.dataset.date,
          startTime: checkbox.dataset.startTime,
          endTime: checkbox.dataset.endTime,
          isDressRehearsal: checkbox.dataset.isDressRehearsal === 'true',
        });
        // Consumed immediately: injectGeneratedCreate() always appends a new pending row, so a
        // second Apply on a still-checked box (a partial refusal below, or re-opening the modal
        // without a fresh Preview) would append a duplicate rather than a no-op (issue #222 review).
        checkbox.checked = false;
      });

      region.querySelectorAll('.rs-generation-retime-checkbox:checked').forEach((checkbox) => {
        const applied = scheduleEdit.injectGeneratedRetime({
          rehearsalId: checkbox.dataset.rehearsalId,
          startTime: checkbox.dataset.startTime,
          endTime: checkbox.dataset.endTime,
        });
        if (!applied) {
          refused.push(checkbox.dataset.date);
        }
      });

      region.querySelectorAll('.rs-generation-orphan-checkbox:checked').forEach((checkbox) => {
        const applied = scheduleEdit.injectGeneratedOrphanDelete({ rehearsalId: checkbox.dataset.rehearsalId });
        if (!applied) {
          refused.push(checkbox.dataset.rehearsalId);
        }
      });

      scheduleEdit.afterApplyGeneration();
      if (refused.length) {
        this.previewError = `Skipped ${refused.length} row${refused.length === 1 ? '' : 's'} you'd already edited on the grid below -- reload and reapply if you still want them changed.`;
        return;
      }
      this.close();
    },
  }));
});
