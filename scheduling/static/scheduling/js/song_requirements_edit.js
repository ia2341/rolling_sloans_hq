// The Song requirements edit table: a repeatable "+ Add requirement" row (issue #209), cloned from a
// <template> holding the add formset's own empty_form, the same __prefix__-substitution idiom
// setlist_edit.js's addRow() uses. Registered once at page load (this file is loaded outside the
// htmx-swapped fragment), so Alpine's own mutation observer picks up the grid whether it arrives as a
// full page or an htmx swap.
document.addEventListener('alpine:init', () => {
  Alpine.data('songRequirementsEdit', () => ({
    init() {
      this.excludeSelectedRoles();
    },

    // Appends a brand-new add-row at the next never-before-used formset slot, substituting the
    // template's literal "__prefix__" token for that slot's numeric index -- the same token Django's
    // own formset.empty_form embeds in every name/id it renders.
    addRow() {
      // Bound on the "+ Add requirement" button, so `$el` here is that
      // button, not the component root -- use `$root` (issue #290).
      const template = this.$root.querySelector('#song-requirement-empty-form-template');
      const rows = this.$root.querySelector('#song-requirement-add-rows');
      const totalForms = this.$root.querySelector('[name="add-TOTAL_FORMS"]');
      const nextIndex = Number(totalForms.value);
      const html = template.innerHTML.replaceAll('__prefix__', String(nextIndex));
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      const row = wrapper.firstElementChild;
      rows.appendChild(row);
      totalForms.value = String(nextIndex + 1);
      // htmx only auto-wires elements present at its own initial scan -- a plain DOM append needs an
      // explicit process() call before the new row's "Add Role" button's hx-post will fire.
      if (window.htmx) {
        window.htmx.process(row);
      }
      this.excludeSelectedRoles();
      const select = row.querySelector('select');
      if (select) {
        select.focus();
      }
    },

    // Disables a Role option on every add-row select where that Role is already chosen on a sibling
    // add-row, so two rows can never submit the same Role -- the picker excluding "any Role already in
    // the pending edits" the issue asks for, client-side. The server's own duplicate check
    // (BaseSongRequirementAddFormSet.clean()) is the backstop against a hand-crafted POST.
    excludeSelectedRoles() {
      // Bound via @change/@htmx:after-swap.window on the component root, so
      // `$el` is safe there -- but this is also called from init() and from
      // addRow() (button-bound), so it must resolve via `$root` regardless
      // of which call site reached it (issue #290).
      const selects = Array.from(this.$root.querySelectorAll('.song-requirement-role-select'));
      const chosenElsewhere = (select) => selects
        .filter((other) => other !== select && other.value)
        .map((other) => other.value);
      selects.forEach((select) => {
        const excluded = new Set(chosenElsewhere(select));
        Array.from(select.options).forEach((option) => {
          if (option.value) {
            option.disabled = excluded.has(option.value);
          }
        });
      });
    },
  }));
});
