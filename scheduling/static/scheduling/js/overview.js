// Instant sort/filter for the Overview page's song-progress table (issue #93). No page reload, no shared library.
document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('song-progress-table');
  if (!table) {
    return;
  }

  const tbody = table.querySelector('tbody');
  const mySongsOnlyCheckbox = document.getElementById('my-songs-only');
  const sortButtons = document.querySelectorAll('[data-sort]');

  sortButtons.forEach((button) => {
    button.addEventListener('click', () => sortRows(button.dataset.sort));
  });

  if (mySongsOnlyCheckbox) {
    mySongsOnlyCheckbox.addEventListener('change', applyFilter);
  }

  function sortRows(sortKey) {
    const rows = Array.from(tbody.querySelectorAll('tr'));
    rows.sort((rowA, rowB) => {
      if (sortKey === 'position') {
        return Number(rowA.dataset.position) - Number(rowB.dataset.position);
      }
      return rowA.dataset.title.localeCompare(rowB.dataset.title);
    });
    rows.forEach((row) => tbody.appendChild(row));
  }

  function applyFilter() {
    const mySongsOnly = mySongsOnlyCheckbox.checked;
    tbody.querySelectorAll('tr').forEach((row) => {
      const hasAssignment = row.dataset.hasAssignment === 'true';
      row.hidden = mySongsOnly && !hasAssignment;
    });
  }
});
