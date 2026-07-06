# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

"""Zentrale Registry der verfügbaren Connectoren.

Muster wie `documents/parsers/registry.py`: ein `dict[type_id → Plugin]`.
Konkrete Connectoren registrieren sich, indem sie `register(...)` aufrufen und
unten importiert werden (aktiv, sobald der erste Connector — TED, Phase 3 —
existiert). Ob ein registrierter Connector tatsächlich nutzbar ist, entscheidet
zusätzlich der Plattform-Toggle (Phase 2).
"""

from govdesk.connectors.base import ConnectorPlugin


class UnknownConnectorError(Exception):
    """Kein Connector mit dieser type_id registriert."""


_CONNECTORS: dict[str, ConnectorPlugin] = {}


def register(plugin: ConnectorPlugin) -> None:
    if plugin.type_id in _CONNECTORS:
        raise ValueError(f"Connector „{plugin.type_id}“ ist bereits registriert")
    _CONNECTORS[plugin.type_id] = plugin


def get_connector(type_id: str) -> ConnectorPlugin:
    plugin = _CONNECTORS.get(type_id)
    if plugin is None:
        raise UnknownConnectorError(f"Unbekannter Connector: {type_id}")
    return plugin


def all_connectors() -> list[ConnectorPlugin]:
    return list(_CONNECTORS.values())


# Konkrete Connectoren hier importieren, damit ihr Modul-Import sie via
# register(...) einträgt. Der Import steht bewusst am Dateiende, nachdem
# register() definiert ist (die Connectoren importieren register von hier).
from govdesk.connectors.ted import plugin as _ted  # noqa: E402, F401
