// The Roster edit surface: the Save button's one-dialog-per-batch removal confirmation, and the
// "Preview unavailable" note when a Role/Remove toggle's htmx Preview request fails (issue #228,
// ADR 0008). Registered once at page load (this file is loaded outside the htmx-swapped fragment),
// so Alpine's own mutation observer picks up and initializes the surface whether it arrives as a
// full page or an htmx swap into #roster-surface.
document.addEventListener('alpine:init', () => {
  Alpine.data('rosterEdit', (confirmUrl) => ({
    confirmHtml: '',
    confirmUrl,
    confirmError: '',
    previewError: '',

    // Any checked 'remove' checkbox means Save must show the batch confirmation dialog first --
    // one dialog for the whole batch, never one per removed person.
    hasPendingRemovals() {
      return Array.from(this.$el.querySelectorAll('.roster-remove-checkbox')).some((checkbox) => checkbox.checked);
    },

    // Fetches the removal confirmation and only opens the dialog on a successful response -- a
    // failed request must never let 'Remove Anyway' submit the destructive Save without the admin
    // having seen the collateral counts, so it surfaces a retryable error instead.
    async onSubmit(event) {
      if (!this.hasPendingRemovals()) {
        return;
      }
      event.preventDefault();
      this.confirmError = '';
      const form = document.getElementById('roster-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData(form);
      let response;
      try {
        response = await fetch(this.confirmUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
          body,
        });
      } catch (error) {
        this.confirmError = 'Could not reach the server to confirm removals. Check your connection and click Save Changes again.';
        return;
      }
      if (!response.ok) {
        this.confirmError = 'Could not load the removal confirmation. Click Save Changes again to retry.';
        return;
      }
      this.confirmHtml = await response.text();
      this.$refs.removalDialog.showModal();
    },

    confirmRemoval() {
      this.$refs.removalDialog.close();
      // .submit() (unlike .requestSubmit()) fires no 'submit' event, so this bypasses onSubmit's
      // confirmation gate on the second pass -- the admin already saw and accepted the Fallout.
      document.getElementById('roster-edit-form').submit();
    },

    cancelRemoval() {
      this.$refs.removalDialog.close();
    },

    // A failed Preview (network error or non-2xx from the debounced Role/Remove toggle) must never
    // read as data loss: the Fallout region is left exactly as it was (htmx only swaps it on a
    // successful response), an inline note says so explicitly, and Save stays enabled -- Save
    // recomputes and revalidates everything server-side regardless (issue #228).
    onPreviewError() {
      this.previewError = 'Preview unavailable right now — your edits are still here, and Save is still enabled.';
    },

    onPreviewSettled() {
      this.previewError = '';
    },
  }));
});
