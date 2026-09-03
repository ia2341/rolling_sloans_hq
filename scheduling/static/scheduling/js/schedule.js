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

// Conditional arrival/departure time-input visibility for the availability blocks'
// inline declare/edit forms (issues #98, #190 — moved here when /me/conflicts/ and its
// own conflicts.js were deleted and availability folded into /schedule/).
// Full absence shows neither time input; late arrival shows only the arrival input;
// early departure shows only the departure input.
document.addEventListener('DOMContentLoaded', function () {
  document.querySelectorAll('.conflict-declare-form').forEach(function (form) {
    var radios = form.querySelectorAll('input[type="radio"]');
    var timeFields = form.querySelectorAll('.conflict-time-field');

    function updateVisibility() {
      var selected = form.querySelector('input[type="radio"]:checked');
      var selectedValue = selected ? selected.value : null;
      timeFields.forEach(function (field) {
        field.hidden = field.dataset.showsFor !== selectedValue;
      });
    }

    radios.forEach(function (radio) {
      radio.addEventListener('change', updateVisibility);
    });
    updateVisibility();
  });
});
