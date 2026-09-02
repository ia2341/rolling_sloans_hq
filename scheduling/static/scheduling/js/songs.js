// Instant sort toggle for the Songs page's setlist table (issue #103). No page reload, no shared library.
document.addEventListener('DOMContentLoaded', () => {
  const table = document.getElementById('setlist-table');
  if (!table) {
    return;
  }

  const tbody = table.querySelector('tbody');
  const sortButtons = document.querySelectorAll('[data-sort]');

  sortButtons.forEach((button) => {
    button.addEventListener('click', () => sortRows(button.dataset.sort));
  });

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
});
