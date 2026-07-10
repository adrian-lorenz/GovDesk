// SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
//
// SPDX-License-Identifier: EUPL-1.2

// Dokumenten-Editor: Autospeichern mit Konflikt-Erkennung, Long-Poll-Sync,
// Word-ähnliches Ribbon (contenteditable + execCommand) und KI-Assistent
// (Fragen zum Dokument / Inline-Überarbeitung mit Projekt-Kontext).
//
// Das Script wird pro Seitenaufruf (auch HTMX-Boost) erneut ausgeführt;
// alle Element-Listener hängen an frischen Elementen. Der Poll-Loop endet,
// sobald der Editor nicht mehr im Dokument hängt (Navigation weg).
(function () {
  "use strict";

  var root = document.getElementById("gd-editor");
  if (!root || root.dataset.gdInit) return;
  root.dataset.gdInit = "1";

  var rte = document.getElementById("editor-rte");
  var statusEl = document.getElementById("editor-status");
  var presenceEl = document.getElementById("editor-presence");
  var conflictEl = document.getElementById("editor-conflict");
  var pid = root.dataset.pid, did = root.dataset.did;
  var canEdit = root.dataset.canEdit === "1";
  var version = parseInt(root.dataset.version, 10);
  var lastSeen = version;
  var dirty = false, saving = false, serverContent = null, timer = null;

  function csrf() {
    var e = document.getElementById("gd-csrf");
    return e ? e.getAttribute("data-token") : "";
  }
  function setStatus(t) { statusEl.textContent = t; }
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function markDirty() {
    dirty = true;
    setStatus("Ungespeichert");
    clearTimeout(timer);
    timer = setTimeout(function () { save(false); }, 1200);
  }

  // --- Speichern & Synchronisation -----------------------------------------
  async function save(force) {
    if (!canEdit || saving || (!dirty && !force)) return;
    saving = true; setStatus("Speichert …");
    var body = new URLSearchParams({ content: rte.innerHTML, base_version: String(version) });
    try {
      var r = await fetch("/projects/" + pid + "/editor/" + did + "/save", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": csrf() },
        body: body,
      });
      if (r.status === 409) {
        var c = await r.json();
        serverContent = c.content; conflictEl.hidden = false; conflictEl.dataset.sv = c.version;
        setStatus("Konflikt"); saving = false; return;
      }
      if (!r.ok) throw new Error("HTTP " + r.status);
      var data = await r.json();
      version = data.version; lastSeen = version; dirty = false; setStatus("Gespeichert");
    } catch (e) { setStatus("Fehler beim Speichern"); }
    saving = false;
  }

  async function poll() {
    while (root.isConnected) {
      try {
        var r = await fetch("/projects/" + pid + "/editor/" + did + "/poll?since=" + lastSeen);
        if (!root.isConnected) return;
        if (r.status === 204) continue;
        if (r.status === 200) {
          var data = await r.json();
          lastSeen = data.version;
          if (!dirty) {
            rte.innerHTML = data.content; version = data.version;
            presenceEl.textContent = data.updated_by ? ("zuletzt geändert von " + data.updated_by) : "";
            setStatus("Aktualisiert");
          } else {
            presenceEl.textContent = "Neue Änderungen von " + (data.updated_by || "jemandem")
              + " — beim Speichern zusammenführen";
          }
        } else { await sleep(3000); }
      } catch (e) { await sleep(3000); }
    }
  }

  if (canEdit) {
    rte.addEventListener("input", markDirty);
    window.addEventListener("beforeunload", function () { if (dirty) save(true); });
    document.getElementById("conflict-theirs").addEventListener("click", function () {
      rte.innerHTML = serverContent; version = parseInt(conflictEl.dataset.sv, 10);
      lastSeen = version; dirty = false; conflictEl.hidden = true; setStatus("Serverstand geladen");
    });
    document.getElementById("conflict-mine").addEventListener("click", function () {
      version = parseInt(conflictEl.dataset.sv, 10); conflictEl.hidden = true;
      dirty = true; save(true);
    });
  }

  // --- Umbenennen über das Titel-Feld ---------------------------------------
  var titel = document.getElementById("editor-titel");
  if (canEdit && titel) {
    var lastTitle = titel.value;
    var renameNow = async function () {
      var name = titel.value.trim();
      if (!name || name === lastTitle) { titel.value = lastTitle; return; }
      try {
        var r = await fetch("/projects/" + pid + "/editor/" + did + "/umbenennen", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": csrf() },
          body: new URLSearchParams({ title: name }),
        });
        if (r.ok) { lastTitle = name; document.title = name; }
      } catch (e) { /* Titel bleibt, erneuter Versuch bei nächster Änderung */ }
    };
    titel.addEventListener("blur", renameNow);
    titel.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); titel.blur(); }
    });
  }

  // --- Ribbon ----------------------------------------------------------------
  if (canEdit) {
    document.querySelectorAll(".gd-ribbon [data-cmd], .gd-ribbon [data-link]").forEach(function (btn) {
      // mousedown statt click: die Auswahl im Editor bleibt erhalten.
      btn.addEventListener("mousedown", function (e) {
        e.preventDefault();
        rte.focus();
        if (btn.dataset.cmd) {
          document.execCommand(btn.dataset.cmd, false, null);
        } else if (btn.dataset.link) {
          var url = window.prompt("Link-Adresse (URL):", "https://");
          if (url) document.execCommand("createLink", false, url);
        }
        markDirty();
        ribbonZustand();
      });
    });

    var format = document.getElementById("ribbon-format");
    format.addEventListener("change", function () {
      rte.focus();
      document.execCommand("formatBlock", false, format.value);
      markDirty();
    });

    // Gedrückt-Zustände (Fett/Kursiv/Listen …) und Formatvorlage nachführen.
    var zustandButtons = document.querySelectorAll(".gd-ribbon [data-zustand]");
    function ribbonZustand() {
      if (!root.isConnected) {
        document.removeEventListener("selectionchange", ribbonZustandDebounced);
        return;
      }
      zustandButtons.forEach(function (btn) {
        var an = false;
        try { an = document.queryCommandState(btn.dataset.zustand); } catch (e) { /* egal */ }
        btn.setAttribute("aria-pressed", an ? "true" : "false");
      });
      var sel = window.getSelection();
      if (sel && sel.anchorNode && rte.contains(sel.anchorNode)) {
        var el = sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement;
        var block = el && el.closest("h1, h2, h3, blockquote, pre, p");
        format.value = block ? block.tagName.toLowerCase() : "p";
      }
    }
    var zustandTimer = null;
    function ribbonZustandDebounced() {
      clearTimeout(zustandTimer);
      zustandTimer = setTimeout(ribbonZustand, 120);
    }
    document.addEventListener("selectionchange", ribbonZustandDebounced);
  }

  // --- KI-Assistent -----------------------------------------------------------
  var kiPanel = document.getElementById("ki-panel");
  if (canEdit && kiPanel) {
    var layout = document.getElementById("editor-layout");
    var verlauf = document.getElementById("ki-verlauf");
    var frageFeld = document.getElementById("ki-frage");
    var senden = document.getElementById("ki-senden");
    var auswahlHinweis = document.getElementById("ki-auswahl");
    var auswahlText = document.getElementById("ki-auswahl-text");
    var modus = "frage";
    var laeuft = false;
    var auswahlRange = null;

    // Panel ein-/ausblenden (persistiert je Browser).
    function setPanel(offen) {
      layout.classList.toggle("gd-ki-zu", !offen);
      try { localStorage.setItem("govdesk-ki-panel", offen ? "offen" : "zu"); } catch (e) { /* egal */ }
    }
    var gespeichert = null;
    try { gespeichert = localStorage.getItem("govdesk-ki-panel"); } catch (e) { /* egal */ }
    if (gespeichert === "zu") setPanel(false);
    document.getElementById("ki-toggle").addEventListener("click", function () {
      setPanel(layout.classList.contains("gd-ki-zu"));
    });
    document.getElementById("ki-schliessen").addEventListener("click", function () { setPanel(false); });

    // Modus-Umschalter
    kiPanel.querySelectorAll("[data-ki-modus]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        modus = btn.dataset.kiModus;
        kiPanel.querySelectorAll("[data-ki-modus]").forEach(function (b) {
          b.setAttribute("aria-pressed", b === btn ? "true" : "false");
        });
        frageFeld.placeholder = modus === "frage"
          ? "Frage oder Anweisung …"
          : "z. B. „Formuliere das bürgernäher“ …";
        auswahlAnzeigen();
      });
    });

    // Auswahl bzw. Einfügemarke im Editor merken — beides geht beim Klick ins
    // Panel verloren.
    var cursorRange = null;
    function auswahlMerken() {
      var sel = window.getSelection();
      if (!sel || !sel.rangeCount) return;
      var range = sel.getRangeAt(0);
      if (!rte.contains(range.commonAncestorContainer)) return;
      if (sel.isCollapsed) {
        cursorRange = range.cloneRange();
        auswahlRange = null;
      } else {
        auswahlRange = range.cloneRange();
      }
      auswahlAnzeigen();
    }
    rte.addEventListener("mouseup", auswahlMerken);
    rte.addEventListener("keyup", auswahlMerken);

    function auswahlAnzeigen() {
      var laenge = auswahlRange ? auswahlRange.toString().length : 0;
      if (modus === "bearbeiten") {
        auswahlHinweis.hidden = false;
        auswahlText.textContent = laenge
          ? "Ersetzt die Auswahl (" + laenge + " Zeichen)"
          : "Keine Auswahl — fügt neuen Inhalt an der Einfügemarke ein";
      } else {
        auswahlHinweis.hidden = laenge === 0;
        auswahlText.textContent = laenge ? "Auswahl (" + laenge + " Zeichen) wird mitgesendet" : "";
      }
    }

    function auswahlHtml() {
      if (!auswahlRange) return "";
      var box = document.createElement("div");
      box.appendChild(auswahlRange.cloneContents());
      return box.innerHTML;
    }

    function nachricht(klasse, inhalt, alsHtml) {
      var el = document.createElement("div");
      el.className = "gd-ki-msg " + klasse;
      if (alsHtml) { el.innerHTML = inhalt; } else { el.textContent = inhalt; }
      verlauf.appendChild(el);
      verlauf.scrollTop = verlauf.scrollHeight;
      return el;
    }

    // Antwort-HTML rückgängig-fähig anwenden: insertHTML läuft über den
    // execCommand-Undo-Stack (Strg+Z stellt den vorherigen Stand wieder her).
    // Mit Auswahl wird ersetzt; ohne Auswahl an der Einfügemarke (bzw. am
    // Dokumentende) EINGEFÜGT — nie das ganze Dokument überschrieben.
    function ersatzAnwenden(html) {
      rte.focus();
      var sel = window.getSelection();
      sel.removeAllRanges();
      if (auswahlRange) {
        sel.addRange(auswahlRange);
      } else if (cursorRange) {
        cursorRange.collapse(false);
        sel.addRange(cursorRange);
      } else {
        var ende = document.createRange();
        ende.selectNodeContents(rte);
        ende.collapse(false);
        sel.addRange(ende);
      }
      document.execCommand("insertHTML", false, html);
      auswahlRange = null;
      cursorRange = null;
      auswahlAnzeigen();
      markDirty();
    }

    function statusAnzeigen(el, text) {
      el.innerHTML = "";
      var spinner = document.createElement("span");
      spinner.className = "gd-spinner";
      el.appendChild(spinner);
      el.appendChild(document.createTextNode(" " + text));
      verlauf.scrollTop = verlauf.scrollHeight;
    }

    async function kiSenden() {
      var frage = frageFeld.value.trim();
      if (!frage || laeuft) return;
      laeuft = true;
      senden.disabled = true;
      frageFeld.value = "";
      nachricht("gd-ki-msg--nutzer", frage, false);
      var antwortEl = nachricht("gd-ki-msg--ki", "", false);
      var auswahl = auswahlHtml();
      // Modus zum Sendezeitpunkt einfrieren — Umschalten während des Streams
      // darf die laufende Antwort nicht umdeuten.
      var sendModus = modus;
      var bearbeitet = sendModus === "bearbeiten";
      if (bearbeitet) {
        // Im Bearbeiten-Modus wäre der Token-Strom rohes HTML — statt ihn
        // anzuzeigen, gibt es nur einen Arbeitsstatus.
        statusAnzeigen(antwortEl, auswahl ? "Überarbeitet die Auswahl …" : "Formuliert neuen Inhalt …");
      } else {
        antwortEl.textContent = "…";
      }

      try {
        var r = await fetch("/projects/" + pid + "/editor/" + did + "/ki", {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF-Token": csrf() },
          body: new URLSearchParams({ frage: frage, modus: sendModus, auswahl: auswahl }),
        });
        if (!r.ok || !r.body) throw new Error("HTTP " + r.status);

        // SSE über fetch lesen: Events sind durch Leerzeilen getrennt.
        var reader = r.body.getReader();
        var decoder = new TextDecoder();
        var puffer = "";
        var text = "";
        for (;;) {
          var teil = await reader.read();
          if (teil.done) break;
          puffer += decoder.decode(teil.value, { stream: true });
          var grenze;
          while ((grenze = puffer.indexOf("\n\n")) >= 0) {
            var block = puffer.slice(0, grenze);
            puffer = puffer.slice(grenze + 2);
            var event = "message";
            var daten = [];
            block.split("\n").forEach(function (zeile) {
              if (zeile.startsWith("event: ")) event = zeile.slice(7);
              else if (zeile.startsWith("data: ")) daten.push(zeile.slice(6));
              else if (zeile === "data:") daten.push("");
            });
            var wert = daten.join("\n");
            if (event === "token") {
              // Token sind HTML-escaped — als Text dekodieren und anhängen.
              var tmp = document.createElement("textarea");
              tmp.innerHTML = wert;
              text += tmp.value;
              if (bearbeitet) {
                // Kein HTML-Rohtext im Panel — nur Fortschritt zeigen.
                statusAnzeigen(
                  antwortEl,
                  (auswahl ? "Überarbeitet die Auswahl … " : "Formuliert neuen Inhalt … ")
                    + text.length + " Zeichen"
                );
              } else {
                antwortEl.textContent = text;
                verlauf.scrollTop = verlauf.scrollHeight;
              }
            } else if (event === "done") {
              antwortEl.innerHTML = wert;  // serverseitig gerendert & gesäubert
              verlauf.scrollTop = verlauf.scrollHeight;
            } else if (event === "ersatz") {
              ersatzAnwenden(wert);        // serverseitig gesäubertes HTML
              antwortEl.innerHTML = "<p><i aria-hidden=\"true\">check_circle</i> Änderung eingefügt — rückgängig mit Strg+Z.</p>";
            } else if (event === "fehler") {
              antwortEl.textContent = wert;
            }
          }
        }
      } catch (e) {
        antwortEl.textContent = "Der Assistent ist gerade nicht erreichbar.";
      }
      laeuft = false;
      senden.disabled = false;
    }

    senden.addEventListener("click", kiSenden);
    frageFeld.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); kiSenden(); }
    });
    auswahlAnzeigen();
  }

  setStatus(canEdit ? "Gespeichert" : "Nur lesen");
  poll();
})();
