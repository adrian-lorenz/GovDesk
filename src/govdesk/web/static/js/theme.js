// SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
//
// SPDX-License-Identifier: EUPL-1.2

// Hell/Dunkel-Umschaltung: persistiert in localStorage + Cookie (für SSR).
(function () {
  "use strict";

  function currentMode() {
    return document.body.classList.contains("dark") ? "dark" : "light";
  }

  function applyMode(mode) {
    document.body.classList.remove("dark", "light");
    document.body.classList.add(mode);
    if (typeof ui === "function") {
      ui("mode", mode);
    }
    var icons = document.querySelectorAll("[data-theme-icon]");
    icons.forEach(function (el) {
      el.textContent = mode === "dark" ? "light_mode" : "dark_mode";
    });
  }

  window.gdToggleTheme = function () {
    var mode = currentMode() === "dark" ? "light" : "dark";
    applyMode(mode);
    try {
      localStorage.setItem("govdesk-theme", mode);
    } catch (e) { /* Speicher gesperrt — Cookie reicht */ }
    document.cookie =
      "govdesk_theme=" + mode + "; Path=/; Max-Age=31536000; SameSite=Lax";
  };

  // Beers Float-Label überlagert sonst den Feldinhalt:
  //  a) Feld OHNE placeholder + Wert  → Label schwebt nicht → überlagert Wert.
  //  b) Feld MIT echtem placeholder    → Label schwebt erst, wenn placeholder
  //     verschwindet → im Leerzustand überlagert das Label den placeholder.
  // Fix: (a) leeren placeholder setzen; (b) Label dauerhaft „active" schweben
  // lassen (auf input UND label — input.active schneidet die Rundungs-Kerbe).
  function fixFloatingLabels(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll(".field.label > input, .field.label > textarea").forEach(function (el) {
      var ph = el.getAttribute("placeholder");
      var hasRealPlaceholder = ph !== null && ph.trim() !== "";
      if (ph === null) {
        el.setAttribute("placeholder", " ");
      }
      if (hasRealPlaceholder) {
        el.classList.add("active");
        var label = el.parentElement && el.parentElement.querySelector("label");
        if (label) label.classList.add("active");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    applyMode(currentMode());
    fixFloatingLabels(document);
  });

  // Nach HTMX-Swaps neue Felder ebenfalls korrigieren.
  document.body.addEventListener("htmx:afterSettle", function (e) {
    fixFloatingLabels(e.target);
  });

  // CSRF-Header für ALLE HTMX-Requests aus #gd-csrf setzen. Das Element liegt
  // im Body und wird bei Boost-Swaps miterneuert — anders als <body>-Attribute,
  // die nach einem Boost-Login veralten würden (führte zu 403 bei allen POSTs).
  document.body.addEventListener("htmx:configRequest", function (e) {
    var el = document.getElementById("gd-csrf");
    var token = el && el.getAttribute("data-token");
    if (token) {
      e.detail.headers["X-CSRF-Token"] = token;
    }
  });

  // Globales Feedback: Fortschrittsbalken oben + Warte-Cursor, solange ein
  // HTMX-Request läuft (Zähler für parallele Requests).
  var active = 0;
  function setBusy(delta) {
    active = Math.max(0, active + delta);
    document.body.classList.toggle("gd-loading", active > 0);
  }
  // Eigenes Bestätigungs-Modal statt window.confirm: HTMX feuert htmx:confirm
  // für Elemente mit hx-confirm. Wir zeigen unser Modal und lösen den Request
  // erst nach Bestätigung aus.
  function gdConfirm(question, onOk) {
    var overlay = document.getElementById("gd-confirm-overlay");
    var text = document.getElementById("gd-confirm-text");
    var ok = document.getElementById("gd-confirm-ok");
    var cancel = document.getElementById("gd-confirm-cancel");
    if (!overlay) { if (window.confirm(question)) onOk(); return; }
    text.textContent = question;
    overlay.hidden = false;

    function cleanup() {
      overlay.hidden = true;
      ok.removeEventListener("click", okHandler);
      cancel.removeEventListener("click", cancelHandler);
      overlay.removeEventListener("click", backdropHandler);
    }
    function okHandler() { cleanup(); onOk(); }
    function cancelHandler() { cleanup(); }
    function backdropHandler(e) { if (e.target === overlay) cleanup(); }
    ok.addEventListener("click", okHandler);
    cancel.addEventListener("click", cancelHandler);
    overlay.addEventListener("click", backdropHandler);
    ok.focus();
  }

  document.body.addEventListener("htmx:confirm", function (e) {
    if (!e.detail.question) { return; }  // kein hx-confirm → normal weiter
    e.preventDefault();
    gdConfirm(e.detail.question, function () { e.detail.issueRequest(true); });
  });

  // Schließbare Overlays (z. B. Quellen-Modal): Klick auf Backdrop oder auf ein
  // [data-gd-dismiss]-Element sowie Escape entfernen das Overlay wieder.
  function gdCloseDismissable() {
    document.querySelectorAll(".gd-overlay[data-gd-dismissable]").forEach(function (o) {
      o.remove();
    });
  }
  document.body.addEventListener("click", function (e) {
    var dismiss = e.target.closest("[data-gd-dismiss]");
    if (dismiss) {
      var ov = dismiss.closest(".gd-overlay");
      if (ov) ov.remove();
      return;
    }
    if (
      e.target.classList &&
      e.target.classList.contains("gd-overlay") &&
      e.target.hasAttribute("data-gd-dismissable")
    ) {
      e.target.remove();
    }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") gdCloseDismissable();
  });

  document.body.addEventListener("htmx:beforeRequest", function () { setBusy(1); });
  document.body.addEventListener("htmx:afterRequest", function (e) {
    setBusy(-1);
    // Formulare mit data-reset-on-success nach erfolgreichem Senden leeren.
    // (Ersetzt hx-on, das per new Function() gegen die CSP verstoßen würde.)
    var form = e.target;
    if (
      e.detail && e.detail.successful &&
      form && form.matches && form.matches("form[data-reset-on-success]")
    ) {
      form.reset();
      window.scrollTo(0, document.body.scrollHeight);
    }
  });
})();
