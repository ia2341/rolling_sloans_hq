// "My Songs Only" filter for /schedule/'s assignment matrix (issue #95).
// Pure client-side row hiding — no reload, no URL param, resets on navigation.
document.addEventListener('DOMContentLoaded', function () {
  var checkbox = document.getElementById('my-songs-only-filter');
  var table = document.getElementById('assignment-matrix');
  if (!checkbox || !table) {
    return;
  }
  var rows = table.querySelectorAll('tbody tr[data-song-id]');
  checkbox.addEventListener('change', function () {
    rows.forEach(function (row) {
      row.hidden = checkbox.checked && row.dataset.mine !== 'true';
    });
  });
});
