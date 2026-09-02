// Conditional arrival/departure time-input visibility for /me/conflicts/'s inline declare forms (issue #98).
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

// `?rehearsal=<id>` pre-fill from My Schedule's "Add a conflict" link (issue #100).
// The server marks the matching row with data-preselected="true" — an
// Upcoming row (undeclared) or a History row (already declared), never
// both. Scroll it into view; an Upcoming row also gets its declare form
// focused, standing in for "expand" since it's already always rendered open.
document.addEventListener('DOMContentLoaded', function () {
  var row = document.querySelector('[data-preselected="true"]');
  if (!row) {
    return;
  }
  row.scrollIntoView({ block: 'center' });
  row.classList.add('conflict-preselected');
  var firstField = row.querySelector('.conflict-declare-form input, .conflict-declare-form select, .conflict-declare-form textarea');
  if (firstField) {
    firstField.focus();
  }
});
