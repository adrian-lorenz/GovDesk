# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Abschaltbare Quellen-Connectoren (Plugins).

Jeder Connector implementiert das Protokoll in `base.ConnectorPlugin` und
registriert sich in `registry`. Der generische Worker-Task und die Verwaltungs-UI
(Phase 2) sowie weitere konkrete Fachdaten-Connectoren (Phase 3) docken
über diesen Vertrag an — ohne den Kern anzufassen.
"""
