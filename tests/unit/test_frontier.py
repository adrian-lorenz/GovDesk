# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from govdesk.agents.crawler.frontier import Frontier, extract_links, normalize_url


def test_normalisierung():
    assert normalize_url("HTTPS://Example.DE/pfad#abschnitt") == "https://example.de/pfad"
    assert normalize_url("https://example.de") == "https://example.de/"


def test_frontier_regeln():
    frontier = Frontier(
        "https://www.gesetze-im-internet.de/vgv_2016/",
        max_depth=2,
        max_pages=50,
        include_pattern=r"/vgv_2016/",
        exclude_pattern=r"\.pdf$",
    )
    start = frontier.pop()
    assert start is not None and start[1] == 0

    frontier.add("https://www.gesetze-im-internet.de/vgv_2016/__1.html", 1)
    assert len(frontier) == 1
    # Duplikat
    frontier.add("https://www.gesetze-im-internet.de/vgv_2016/__1.html", 1)
    assert len(frontier) == 1
    # Fremde Domain
    frontier.add("https://example.com/vgv_2016/x.html", 1)
    assert len(frontier) == 1
    # Exclude-Muster
    frontier.add("https://www.gesetze-im-internet.de/vgv_2016/gesamt.pdf", 1)
    assert len(frontier) == 1
    # Include-Muster verfehlt
    frontier.add("https://www.gesetze-im-internet.de/bgb/__433.html", 1)
    assert len(frontier) == 1
    # Zu tief
    frontier.add("https://www.gesetze-im-internet.de/vgv_2016/__2.html", 3)
    assert len(frontier) == 1


def test_link_extraktion():
    html = b'<a href="/a.html">A</a> <a href="mailto:x@y.de">M</a> <a href="b.html#f">B</a>'
    links = extract_links("https://example.de/dir/", html)
    assert "https://example.de/a.html" in links
    assert "https://example.de/dir/b.html" in links
    assert not any(link.startswith("mailto") for link in links)
