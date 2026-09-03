// The Home admin panel's Create Semester door (issue #200): fetches Semester setup's own form
// fragment and shows it in a dialog, so the wizard opens as a modal over Home without a second
// template for the step. The dialog's form still posts to the real endpoint and navigates on
// submit -- this only saves the admin a full page load to *open* the form, never a second write
// path, and the "Create Semester" link works as a plain page navigation with this script unavailable.
document.addEventListener('alpine:init', () => {
  Alpine.data('semesterSetupModal', (setupUrl) => ({
    content: '',

    async open() {
      let response;
      try {
        response = await fetch(setupUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      } catch (error) {
        window.location.href = setupUrl;
        return;
      }
      if (!response.ok) {
        window.location.href = setupUrl;
        return;
      }
      this.content = await response.text();
      this.$refs.dialog.showModal();
    },

    close() {
      this.$refs.dialog.close();
    },
  }));
});
