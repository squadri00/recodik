// MyVault client-side helpers. Vanilla JS only -- no framework, no build step.
"use strict";

// Field builder: show the "options" textarea only for types that use it
// (dropdown / multi-select). Progressive -- the field still works without JS.
document.querySelectorAll("[data-field-form]").forEach(function (form) {
  var select = form.querySelector("[data-field-type]");
  var wrap = form.querySelector("[data-options-wrap]");
  if (!select || !wrap) return;
  function sync() {
    var opt = select.options[select.selectedIndex];
    wrap.hidden = !(opt && opt.dataset.options === "1");
  }
  select.addEventListener("change", sync);
  sync();
});
