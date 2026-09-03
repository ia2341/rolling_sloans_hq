document.addEventListener('alpine:init', () => {
  Alpine.data('rosterImportStep', () => ({
    filter: '',
    matches(name) {
      return !this.filter || name.toLowerCase().includes(this.filter.toLowerCase());
    },
    selectAll() {
      this.$root.querySelectorAll('.roster-import-checkbox').forEach((checkbox) => { checkbox.checked = true; });
    },
    selectNone() {
      this.$root.querySelectorAll('.roster-import-checkbox').forEach((checkbox) => { checkbox.checked = false; });
    },
  }));
});
