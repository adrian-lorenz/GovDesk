// SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
//
// SPDX-License-Identifier: EUPL-1.2

// Hell/Dunkel-Umschaltung: persistiert in localStorage + Cookie (für SSR).
(function () {
  "use strict";

  function currentMode() {
    return document.body.classList.contains("kern-dark") ? "dark" : "light";
  }

  function applyMode(mode) {
    document.body.classList.remove("kern-dark", "kern-light");
    document.body.classList.add(mode === "dark" ? "kern-dark" : "kern-light");
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

  document.addEventListener("DOMContentLoaded", function () {
    applyMode(currentMode());
    initSidenav(document);
  });

  // Projekt-Seitenleiste: einklappbare Minibar. Nutzerwahl in localStorage;
  // ohne Nutzerwahl gilt der Seiten-Default (data-gd-mini-default, z. B. Editor).
  function initSidenav(root) {
    var nav = (root.querySelector ? root : document).querySelector("#gd-projekt-sidenav");
    if (!nav || nav.dataset.gdMiniInit) return;
    nav.dataset.gdMiniInit = "1";
    var gespeichert = null;
    try { gespeichert = localStorage.getItem("govdesk-sidenav"); } catch (e) { /* egal */ }
    var mini = gespeichert !== null
      ? gespeichert === "mini"
      : nav.dataset.gdMiniDefault === "1";
    setMini(mini);

    var toggle = nav.querySelector("[data-gd-sidenav-toggle]");
    if (toggle) {
      toggle.addEventListener("click", function () {
        mini = !nav.classList.contains("gd-sidenav--mini");
        setMini(mini);
        try { localStorage.setItem("govdesk-sidenav", mini ? "mini" : "voll"); } catch (e) { /* egal */ }
      });
    }
    function setMini(an) {
      nav.classList.toggle("gd-sidenav--mini", an);
      var icon = nav.querySelector("[data-gd-sidenav-icon]");
      if (icon) icon.textContent = an ? "chevron_right" : "chevron_left";
    }
  }

  // Nach HTMX-Boost-Swaps neu initialisieren (Body-Inhalt wurde ersetzt).
  document.body.addEventListener("htmx:afterSettle", function (e) {
    initSidenav(e.target === document.body ? document : e.target);
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

  // Auch für Seiten-Skripte nutzbar (z. B. Explorer-Kontextmenü).
  window.gdConfirm = gdConfirm;

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
    // Tastatur-Aktivierung für klickbare Nicht-Buttons (z. B. Quellen in der
    // Sidebar). Ersetzt HTMX-Event-Filter wie keyup[key=='Enter'], die per
    // Function() kompiliert würden — das verbietet unsere CSP (kein eval).
    if (e.key === "Enter" || e.key === " ") {
      var t = e.target.closest && e.target.closest("[data-gd-enter-click]");
      if (t) {
        e.preventDefault();
        t.click();
      }
    }
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
