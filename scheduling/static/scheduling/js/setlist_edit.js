// The setlist edit grid: drag/keyboard reorder, repeatable add, and undoable strike-through delete (issue #179).
// Registered once at page load (this file is loaded outside the htmx-swapped fragment), so Alpine's own
// mutation observer picks up and initializes the grid whether it arrives as a full page or an htmx swap.
document.addEventListener('alpine:init', () => {
  Alpine.data('setlistEdit', (confirmUrl) => ({
    confirmHtml: '',
    confirmUrl,
    deleteError: '',
    sortable: null,

    init() {
      const rows = this.$el.querySelector('#setlist-edit-rows');
      if (!rows) {
        return;
      }
      this.sortable = Sortable.create(rows, {
        handle: '.setlist-drag-handle',
        animation: 150,
        onEnd: () => this.reindex(),
      });
      this.reindex();
    },

    // Appends a brand-new row at the next never-before-used formset slot (>= INITIAL_FORMS, so Django's
    // own initial/extra split always treats it as new -- see _save_buffer's docstring). Unlike drag/move,
    // this is the one place a slot index gets assigned, and it happens exactly once, at creation.
    addRow() {
      const template = this.$el.querySelector('#setlist-empty-form-template');
      const rows = this.$el.querySelector('#setlist-edit-rows');
      const totalForms = this.$el.querySelector('[name$="-TOTAL_FORMS"]');
      const nextIndex = Number(totalForms.value);
      const clone = template.content.cloneNode(true);
      clone.querySelectorAll('[name]').forEach((field) => {
        field.name = field.name.replace('__prefix__', String(nextIndex));
      });
      const orderField = clone.querySelector('.song-order-field');
      orderField.value = `song-${nextIndex}`;
      rows.appendChild(clone);
      totalForms.value = String(nextIndex + 1);
      this.reindex();
      const addedGroup = rows.lastElementChild;
      const titleInput = addedGroup.querySelector('input[name$="-title"]');
      if (titleInput) {
        titleInput.focus();
      }
    },

    moveUp(event) {
      const group = event.target.closest('.setlist-edit-row-group');
      const previous = group.previousElementSibling;
      if (previous) {
        group.parentElement.insertBefore(group, previous);
        this.reindex();
      }
    },

    moveDown(event) {
      const group = event.target.closest('.setlist-edit-row-group');
      const next = group.nextElementSibling;
      if (next) {
        group.parentElement.insertBefore(next, group);
        this.reindex();
      }
    },

    toggleDelete(event) {
      const group = event.target.closest('.setlist-edit-row-group');
      const checkbox = group.querySelector('.song-delete-checkbox-wrapper input');
      checkbox.checked = !checkbox.checked;
      this.reindex();
    },

    // Recomputes the `#` column from the buffer's current DOM order -- a row's formset slot (song-N-*)
    // never changes here (see _save_buffer's docstring for why), only which visible number it shows and
    // whether it reads as struck. The submitted *order* comes from each row's song_order field, which
    // travels with it for free since SortableJS/moveUp/moveDown move the whole row-group node.
    reindex() {
      const rows = this.$el.querySelector('#setlist-edit-rows');
      const groups = Array.from(rows.children);
      let visibleNumber = 0;
      groups.forEach((group) => {
        const checkbox = group.querySelector('.song-delete-checkbox-wrapper input');
        const deleted = checkbox.checked;
        group.classList.toggle('setlist-row-deleted', deleted);
        const numberCell = group.querySelector('.setlist-row-number');
        if (deleted) {
          numberCell.textContent = '—';
        } else {
          visibleNumber += 1;
          numberCell.textContent = String(visibleNumber);
        }
        const deleteButton = group.querySelector('.setlist-delete-toggle');
        if (deleteButton) {
          deleteButton.textContent = deleted ? 'Undo' : 'Delete';
        }
      });
    },

    deletedSongIds() {
      return Array.from(this.$el.querySelectorAll('.setlist-edit-row-group'))
        .filter((group) => group.dataset.songId && group.querySelector('.song-delete-checkbox-wrapper input').checked)
        .map((group) => group.dataset.songId);
    },

    // Fetches the deletion confirmation and only opens the dialog on a successful response --
    // a failed request must never let 'Delete Anyway' submit the destructive Save without the
    // admin having seen the recording/uploader counts, so it surfaces a retryable error instead.
    async onSubmit(event) {
      const songIds = this.deletedSongIds();
      if (songIds.length === 0) {
        return;
      }
      event.preventDefault();
      this.deleteError = '';
      const form = document.getElementById('setlist-edit-form');
      const csrfToken = form.querySelector('[name=csrfmiddlewaretoken]').value;
      const body = new FormData();
      songIds.forEach((songId) => body.append('song_id', songId));
      let response;
      try {
        response = await fetch(this.confirmUrl, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken },
          body,
        });
      } catch (error) {
        this.deleteError = 'Could not reach the server to confirm deletions. Check your connection and click Save Changes again.';
        return;
      }
      if (!response.ok) {
        this.deleteError = 'Could not load the deletion confirmation. Click Save Changes again to retry.';
        return;
      }
      this.confirmHtml = await response.text();
      this.$refs.deleteDialog.showModal();
    },

    confirmDelete() {
      this.$refs.deleteDialog.close();
      // .submit() (unlike .requestSubmit()) fires no 'submit' event, so this bypasses onSubmit's
      // confirmation gate on the second pass -- the admin already saw and accepted the counts.
      document.getElementById('setlist-edit-form').submit();
    },

    cancelDelete() {
      this.$refs.deleteDialog.close();
    },
  }));
});
