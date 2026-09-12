// MyVault client-side helpers. Vanilla JS only -- no framework, no build step.
"use strict";

// --- Field builder: options textarea shows only for option types -------------
document.querySelectorAll("[data-field-form]").forEach(function (form) {
  var select = form.querySelector("[data-field-type]");
  var optionsWrap = form.querySelector("[data-options-wrap]");
  var targetWrap = form.querySelector("[data-target-wrap]");
  var alertWrap = form.querySelector("[data-alert-wrap]");
  var encryptWrap = form.querySelector("[data-encrypt-wrap]");
  if (!select) return;
  function sync() {
    var opt = select.options[select.selectedIndex];
    if (optionsWrap) optionsWrap.hidden = !(opt && opt.dataset.options === "1");
    if (targetWrap) targetWrap.hidden = !(opt && opt.dataset.target === "1");
    if (alertWrap) alertWrap.hidden = !(opt && opt.dataset.alert === "1");
    if (encryptWrap) encryptWrap.hidden = !(opt && opt.value === "password");
  }
  select.addEventListener("change", sync);
  sync();
});

// --- Encrypted field reveal / copy -----------------------------------------
// Masked by default. On "Reveal" we POST to the reveal endpoint and show the
// decrypted value plus a Copy button. Plaintext never sits in the initial HTML.
document.addEventListener("click", function (e) {
  var btn = e.target.closest("[data-reveal]");
  if (!btn) return;
  e.preventDefault();

  var out = btn.parentElement.querySelector(".reveal-out");
  if (!out) return;

  if (out.dataset.shown === "1") {
    out.textContent = "";
    out.dataset.shown = "0";
    btn.textContent = "Reveal";
    return;
  }

  btn.disabled = true;
  var body = new URLSearchParams({ field_key: btn.dataset.field });
  fetch("/records/" + encodeURIComponent(btn.dataset.record) + "/reveal", {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-Requested-With": "fetch" },
    body: body,
  })
    .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
    .then(function (res) {
      if (!res.ok) {
        out.textContent = " " + (res.j.error || "Could not reveal.");
        out.className = "reveal-out reveal-err";
        return;
      }
      out.className = "reveal-out";
      out.dataset.shown = "1";
      btn.textContent = "Hide";
      renderRevealed(out, res.j.value);
    })
    .catch(function () {
      out.textContent = " Network error.";
      out.className = "reveal-out reveal-err";
    })
    .finally(function () { btn.disabled = false; });
});

// --- Expiry/reminder alert dropdown -----------------------------------------
document.querySelectorAll("[data-alert-toggle]").forEach(function (btn) {
  var wrap = btn.closest(".alert-badge-wrap");
  var dropdown = wrap && wrap.querySelector("[data-alert-dropdown]");
  if (!dropdown) return;
  btn.addEventListener("click", function (e) {
    e.stopPropagation();
    dropdown.hidden = !dropdown.hidden;
  });
  document.addEventListener("click", function (e) {
    if (!dropdown.hidden && !wrap.contains(e.target)) dropdown.hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") dropdown.hidden = true;
  });
});

// --- Markdown toolbar for `textarea` fields ---------------------------------
// Inserts plain Markdown syntax around the current selection. No editor
// library -- the field stays a normal <textarea>, formatting just gets
// rendered when you view the record (see myvault/richtext.py).
document.querySelectorAll("[data-md-toolbar]").forEach(function (bar) {
  var ta = document.getElementById(bar.dataset.for);
  if (!ta) return;
  bar.querySelectorAll("[data-md]").forEach(function (btn) {
    btn.addEventListener("click", function () { applyMarkdown(ta, btn.dataset.md); });
  });
});

function applyMarkdown(ta, kind) {
  var start = ta.selectionStart, end = ta.selectionEnd;
  var value = ta.value;
  var selected = value.slice(start, end);
  var before = value.slice(0, start), after = value.slice(end);

  function wrap(left, right, placeholder) {
    var text = selected || placeholder;
    ta.value = before + left + text + right + after;
    var selStart = before.length + left.length;
    ta.setSelectionRange(selStart, selStart + text.length);
  }

  function prefixLines(makeLine) {
    var lineStart = value.lastIndexOf("\n", start - 1) + 1;
    var lineEnd = value.indexOf("\n", end);
    if (lineEnd === -1) lineEnd = value.length;
    var block = value.slice(lineStart, lineEnd);
    var lines = block.split("\n").map(makeLine);
    var joined = lines.join("\n");
    ta.value = value.slice(0, lineStart) + joined + value.slice(lineEnd);
    ta.setSelectionRange(lineStart, lineStart + joined.length);
  }

  switch (kind) {
    case "bold": wrap("**", "**", "bold text"); break;
    case "italic": wrap("_", "_", "italic text"); break;
    case "code": wrap("`", "`", "code"); break;
    case "link": {
      var url = window.prompt("Link URL:", "https://");
      if (url === null) return;
      wrap("[", "](" + url + ")", "link text");
      break;
    }
    case "h2": prefixLines(function (ln) { return /^##\s/.test(ln) ? ln.replace(/^##\s/, "") : "## " + ln; }); break;
    case "ul": prefixLines(function (ln) { return /^-\s/.test(ln) ? ln : "- " + ln; }); break;
    case "ol": prefixLines(function (ln, i) { return /^\d+\.\s/.test(ln) ? ln : (i + 1) + ". " + ln; }); break;
  }
  ta.focus();
}

function renderRevealed(out, value) {
  out.textContent = "";
  var code = document.createElement("code");
  code.className = "revealed-value";
  code.textContent = value === "" ? "(empty)" : value;
  out.appendChild(code);

  if (value !== "" && navigator.clipboard) {
    var copy = document.createElement("button");
    copy.type = "button";
    copy.className = "linkbtn";
    copy.textContent = "Copy";
    copy.addEventListener("click", function () {
      navigator.clipboard.writeText(value).then(function () {
        copy.textContent = "Copied";
        setTimeout(function () { copy.textContent = "Copy"; }, 1200);
      });
    });
    out.appendChild(document.createTextNode(" "));
    out.appendChild(copy);
  }
}
