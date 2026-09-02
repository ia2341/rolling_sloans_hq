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
