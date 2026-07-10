// SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
//
// SPDX-License-Identifier: EUPL-1.2

// Explorer der Dokumentenbibliothek: Kontextmenü, Umbenennen, Löschen,
// Drag & Drop zum Verschieben in Ordner bzw. auf die Pfadleiste.
// Delegierte Listener werden nur einmal registriert (Guard), damit
// HTMX-Boost-Swaps, die dieses Script erneut ausführen, nichts doppeln.
(function () {
  "use strict";
  if (window.gdExplorerInit) return;
  window.gdExplorerInit = true;

  function explorer() { return document.getElementById("gd-explorer"); }
  function canEdit() {
    var ex = explorer();
    return ex && ex.dataset.canEdit === "1";
  }
  function pid() { return explorer().dataset.pid; }
  function csrf() {
    var e = document.getElementById("gd-csrf");
    return e ? e.getAttribute("data-token") : "";
  }

  async function post(url, felder) {
    var r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": csrf() },
      body: new URLSearchParams(felder || {}),
    });
    if (!r.ok && r.status !== 204) throw new Error("HTTP " + r.status);
    return r;
  }

  function neuLaden() { window.location.reload(); }

  // --- Dialoge -------------------------------------------------------------
  function dialogOeffnen(id, fokusId) {
    var dlg = document.getElementById(id);
    if (!dlg) return null;
    dlg.showModal();
    if (fokusId) {
      var f = document.getElementById(fokusId);
      if (f) { f.focus(); f.select && f.select(); }
    }
    return dlg;
  }

  document.addEventListener("click", function (e) {
    if (!e.target.closest) return;
    if (e.target.closest("#btn-neues-dokument")) dialogOeffnen("dlg-neues-dokument", "dlg-dok-titel");
    if (e.target.closest("#btn-neuer-ordner")) dialogOeffnen("dlg-neuer-ordner", "dlg-ordner-name");
    var zu = e.target.closest("[data-dlg-schliessen]");
    if (zu) {
      var dlg = zu.closest("dialog");
      if (dlg) dlg.close();
    }
  });

  // --- Kontextmenü ---------------------------------------------------------
  var ctxKachel = null;

  function ctxMenue() { return document.getElementById("gd-ctx-menu"); }

  function ctxSchliessen() {
    var m = ctxMenue();
    if (m) m.hidden = true;
    ctxKachel = null;
  }

  document.addEventListener("contextmenu", function (e) {
    if (!e.target.closest) return;
    var kachel = e.target.closest(".gd-tile");
    var m = ctxMenue();
    if (!kachel || !m || !canEdit()) return;
    e.preventDefault();
    ctxKachel = kachel;
    // „Eine Ebene nach oben" nur anbieten, wenn wir in einem Ordner stehen.
    var hoch = document.getElementById("ctx-hoch");
    if (hoch) hoch.hidden = !explorer().dataset.ordner;
    m.hidden = false;
    // Innerhalb des Fensters halten.
    var b = m.getBoundingClientRect();
    m.style.left = Math.min(e.clientX, window.innerWidth - b.width - 8) + "px";
    m.style.top = Math.min(e.clientY, window.innerHeight - b.height - 8) + "px";
  });

  document.addEventListener("click", function (e) {
    var m = ctxMenue();
    if (!m || m.hidden) return;
    var aktion = e.target.closest && e.target.closest("[data-ctx]");
    if (!aktion || !ctxKachel) { ctxSchliessen(); return; }
    var kachel = ctxKachel;
    ctxSchliessen();
    var typ = kachel.dataset.typ, id = kachel.dataset.id, name = kachel.dataset.name;

    if (aktion.dataset.ctx === "oeffnen") {
      window.location.href = kachel.href;
    } else if (aktion.dataset.ctx === "umbenennen") {
      var dlg = dialogOeffnen("dlg-umbenennen", "dlg-umbenennen-name");
      if (!dlg) return;
      var input = document.getElementById("dlg-umbenennen-name");
      input.value = name;
      input.select();
      var form = document.getElementById("form-umbenennen");
      form.dataset.url = typ === "ordner"
        ? "/projects/" + pid() + "/editor/ordner/" + id + "/umbenennen"
        : "/projects/" + pid() + "/editor/" + id + "/umbenennen";
      form.dataset.feld = typ === "ordner" ? "name" : "title";
    } else if (aktion.dataset.ctx === "hoch") {
      // In den Elternordner des aktuellen Ordners verschieben: das Backend
      // kennt nur „Ziel"; die Pfadleiste enthält den Eltern-Link als vorletzten
      // Drop-Punkt — wir lesen ihn von dort.
      var crumbs = document.querySelectorAll(".gd-crumbs [data-drop-ordner]");
      var eltern = crumbs.length ? crumbs[crumbs.length - 1].dataset.dropOrdner : "";
      verschieben(kachel, eltern);
    } else if (aktion.dataset.ctx === "loeschen") {
      var frage = typ === "ordner"
        ? "Ordner „" + name + "“ löschen? Enthaltene Einträge wandern eine Ebene nach oben."
        : "Dokument „" + name + "“ mitsamt Historie löschen?";
      // Bestätigungs-Modal aus theme.js; Fallback: natives confirm.
      if (window.gdConfirm) {
        window.gdConfirm(frage, function () { loeschen(typ, id); });
      } else if (window.confirm(frage)) {
        loeschen(typ, id);
      }
    }
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") ctxSchliessen();
  });

  async function loeschen(typ, id) {
    var url = typ === "ordner"
      ? "/projects/" + pid() + "/editor/ordner/" + id + "/loeschen"
      : "/projects/" + pid() + "/editor/" + id + "/loeschen";
    try { await post(url); neuLaden(); } catch (err) { window.alert("Löschen fehlgeschlagen."); }
  }

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form.matches || !form.matches("#form-umbenennen")) return;
    e.preventDefault();
    var name = document.getElementById("dlg-umbenennen-name").value.trim();
    if (!name) return;
    var felder = {};
    felder[form.dataset.feld] = name;
    post(form.dataset.url, felder)
      .then(neuLaden)
      .catch(function () { window.alert("Umbenennen fehlgeschlagen."); });
  });

  // --- Drag & Drop ----------------------------------------------------------
  var gezogen = null;

  document.addEventListener("dragstart", function (e) {
    if (!e.target.closest || !canEdit()) return;
    var kachel = e.target.closest(".gd-tile[draggable]");
    if (!kachel) return;
    gezogen = kachel;
    kachel.classList.add("gd-tile--dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", kachel.dataset.id);
  });

  document.addEventListener("dragend", function () {
    if (gezogen) gezogen.classList.remove("gd-tile--dragging");
    gezogen = null;
    document.querySelectorAll(".gd-tile--dragover, .gd-crumb-dragover").forEach(function (el) {
      el.classList.remove("gd-tile--dragover", "gd-crumb-dragover");
    });
  });

  function dropZiel(e) {
    if (!e.target.closest) return null;
    var ziel = e.target.closest("[data-drop-ordner]");
    if (!ziel || !gezogen || ziel === gezogen) return null;
    // Ordner nicht auf sich selbst ziehen.
    if (gezogen.dataset.typ === "ordner" && ziel.dataset.dropOrdner === gezogen.dataset.id) return null;
    return ziel;
  }

  document.addEventListener("dragover", function (e) {
    var ziel = dropZiel(e);
    if (!ziel) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    ziel.classList.add(ziel.classList.contains("gd-tile") ? "gd-tile--dragover" : "gd-crumb-dragover");
  });

  document.addEventListener("dragleave", function (e) {
    if (!e.target.closest) return;
    var ziel = e.target.closest("[data-drop-ordner]");
    if (ziel) ziel.classList.remove("gd-tile--dragover", "gd-crumb-dragover");
  });

  document.addEventListener("drop", function (e) {
    var ziel = dropZiel(e);
    if (!ziel) return;
    e.preventDefault();
    var kachel = gezogen;
    gezogen = null;
    verschieben(kachel, ziel.dataset.dropOrdner);
  });

  async function verschieben(kachel, zielOrdner) {
    var url = kachel.dataset.typ === "ordner"
      ? "/projects/" + pid() + "/editor/ordner/" + kachel.dataset.id + "/verschieben"
      : "/projects/" + pid() + "/editor/" + kachel.dataset.id + "/verschieben";
    try {
      await post(url, zielOrdner ? { ziel: zielOrdner } : {});
      neuLaden();
    } catch (err) {
      window.alert("Verschieben fehlgeschlagen.");
    }
  }
})();
