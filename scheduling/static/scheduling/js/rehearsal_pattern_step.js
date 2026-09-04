// Semester setup step 5 (issue #203): a plain repeatable Rehearsal Time list, no Preview/Apply/diff --
// generation itself happens later, on the Rehearsals surface. The "+ Add Rehearsal Time" and
// default-duration-prefill mechanics mirror rehearsal_generation.js's, trimmed to just what this step
// needs: there is no save/preview networking here, since this step's own form POST (not fetch) is the
// only write, and no Skip Date list, since Skip Dates stay a Rehearsals-surface-only concern.
document.addEventListener('alpine:init', () => {
  Alpine.data('rehearsalPatternStep', (defaultDurationMinutes) => ({
    defaultDurationMinutes,

    addRehearsalTimeRow() {
      this._appendRow('rehearsal-time-empty-row-template', 'rehearsal-time-rows-list', 'rehearsal-time');
      const rows = document.getElementById('rehearsal-time-rows-list');
      const rowEl = rows.lastElementChild;
      const startInput = rowEl.querySelector('input[name$="-start_time"]');
      const endInput = rowEl.querySelector('input[name$="-end_time"]');
      // A new Rehearsal Time's end is prefilled from the Semester's default duration (issue #203),
      // derived from whatever start time gets typed -- there's nothing to derive from until then.
      startInput.addEventListener('change', () => {
        if (!endInput.value && startInput.value) {
          endInput.value = this._addMinutes(startInput.value, this.defaultDurationMinutes);
        }
      }, { once: true });
    },

    removeRehearsalTimeRow(event) {
      const row = event.target.closest('.rehearsal-time-row');
      row.querySelector('.rehearsal-time-delete-checkbox-wrapper input').checked = true;
      row.style.display = 'none';
    },

    // Clones a <template>, does __prefix__ -> next index substitution on name/id/label[for], and bumps
    // the formset's own TOTAL_FORMS (mirrors rehearsal_generation.js's/schedule_edit.js's own "+ Add").
    _appendRow(templateId, rowsId, formsetPrefix) {
      // Reached from addRehearsalTimeRow(), bound on the "+ Add Rehearsal
      // Time" button, so `$el` there is that button, not the component root
      // -- use `$root` (issue #290).
      const template = document.getElementById(templateId);
      const rows = document.getElementById(rowsId);
      const totalForms = this.$root.querySelector(`[name="${formsetPrefix}-TOTAL_FORMS"]`);
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

    _addMinutes(hhmm, minutes) {
      const [hours, mins] = hhmm.split(':').map(Number);
      const total = ((hours * 60) + mins + minutes) % (24 * 60);
      const outHours = Math.floor(total / 60);
      const outMinutes = total % 60;
      return `${String(outHours).padStart(2, '0')}:${String(outMinutes).padStart(2, '0')}`;
    },
  }));
});
