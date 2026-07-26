# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from govdesk.rag.retrieval import Citation


def test_citation_speichert_vollstaendigen_admin_kontext():
    content = "A" * 450
    citation = Citation(
        number=1,
        document_id="document-id",
        chunk_index=2,
        filename="quelle.md",
        heading_path="Abschnitt",
        page_no=None,
        source_url=None,
        score=0.123456,
        snippet=content,
    ).as_dict()

    assert citation["snippet"] == content[:300]
    assert citation["content"] == content
    assert citation["score"] == 0.1235
