// MyVault client-side helpers. Vanilla JS only -- no framework, no build step.
"use strict";

// --- Field builder: options textarea shows only for option types -------------
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
