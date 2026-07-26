# SPDX-FileCopyrightText: 2026 GovDesk-Mitwirkende
#
# SPDX-License-Identifier: EUPL-1.2

from govdesk.chat.streaming import MODEL_KNOWLEDGE_NOTICE, NO_SOURCES_ANSWER
from govdesk.web.deps import templates


def test_finale_antwort_aktualisiert_quellen_sidebar_oob():
    rendered = templates.env.get_template("partials/_antwort_final.html").render(
        html_content="<p>Antwort mit Beleg [1].</p>",
        project_id="projekt-id",
        citations=[
            {
                "number": 1,
                "document_id": "dokument-id",
                "chunk_index": 7,
                "filename": "bdsg.md",
                "heading_path": "BDSG > § 1 – Anwendungsbereich",
                "page_no": None,
                "source_url": "https://www.gesetze-im-internet.de/bdsg_2018/",
                "snippet": "Dieses Gesetz gilt für die Verarbeitung personenbezogener Daten.",
            }
        ],
    )

    assert 'id="quellen-sidebar"' in rendered
    assert 'hx-swap-oob="innerHTML"' in rendered
    assert "bdsg.md" in rendered
    assert "§ 1" in rendered
    assert "dokument-id/passage?chunk=7" in rendered


def test_antwort_ohne_retrieval_erfindet_keine_quellennummer():
    assert "[1]" not in NO_SOURCES_ANSWER
    assert "keine passende Quelle" in NO_SOURCES_ANSWER

    rendered = templates.env.get_template("partials/_quellen_sidebar.html").render(
        project_id="projekt-id",
        citations=[],
    )
    assert "keine Quellen aus der Wissensbasis gefunden" in rendered


def test_modellwissen_fallback_wird_in_antwort_und_sidebar_markiert():
    assert "allgemeinem Modellwissen" in MODEL_KNOWLEDGE_NOTICE
    assert "nicht durch Projektquellen belegt" in MODEL_KNOWLEDGE_NOTICE
    assert "[1]" not in MODEL_KNOWLEDGE_NOTICE

    rendered = templates.env.get_template("partials/_antwort_final.html").render(
        html_content="<p>Fallback-Antwort</p>",
        project_id="projekt-id",
        citations=[],
        model_knowledge_used=True,
    )
    assert "Modellwissen" in rendered
    assert "nicht durch die Wissensbasis belegt" in rendered


def test_modellchat_zeigt_dass_rag_bewusst_nicht_verwendet_wurde():
    rendered = templates.env.get_template("partials/_antwort_final.html").render(
        html_content="<p>Normale Modellantwort</p>",
        project_id="projekt-id",
        citations=[],
        model_chat_used=True,
        model_knowledge_used=False,
    )

    assert "Modellchat" in rendered
    assert "bewusst nicht durchsucht" in rendered
    assert "Keine passende Projektquelle gefunden" not in rendered


def test_leerer_modellchat_zeigt_den_aktiven_modus():
    rendered = templates.env.get_template("partials/_quellen_sidebar.html").render(
        project_id="projekt-id",
        citations=[],
        model_chat_used=False,
        model_chat_active=True,
        model_knowledge_used=False,
    )

    assert "In diesem Chat ist die Projekt-Wissensbasis ausgeschaltet" in rendered
    assert "direkt vom ausgewählten Sprachmodell" in rendered


def test_retrieval_details_werden_nur_im_admin_kontext_gerendert():
    citations = [
        {
            "number": 1,
            "document_id": "dokument-id",
            "chunk_index": 3,
            "filename": "bdsg.md",
            "heading_path": "BDSG > § 1",
            "page_no": None,
            "source_url": None,
            "score": 0.87654,
            "snippet": "Kurzer Ausschnitt",
            "content": "Vollständiger vertraulicher Retrieval-Chunk",
        }
    ]
    template = templates.env.get_template("partials/_antwort_final.html")

    admin_html = template.render(
        html_content="<p>Antwort</p>",
        project_id="projekt-id",
        citations=citations,
        show_retrieval_details=True,
    )
    assert "Retrieval-Details (1 Treffer)" in admin_html
    assert "Rang 1" in admin_html
    assert "Score 0.8765" in admin_html
    assert "Vollständiger vertraulicher Retrieval-Chunk" in admin_html

    viewer_html = template.render(
        html_content="<p>Antwort</p>",
        project_id="projekt-id",
        citations=citations,
        show_retrieval_details=False,
    )
    assert "Retrieval-Details" not in viewer_html
    assert "Vollständiger vertraulicher Retrieval-Chunk" not in viewer_html


def test_retrieval_details_akzeptieren_alte_citations_ohne_chunk_index():
    rendered = templates.env.get_template("partials/_retrieval_details.html").render(
        citations=[
            {
                "number": 1,
                "filename": "altbestand.pdf",
                "score": 0.5,
                "snippet": "Historischer Retrieval-Ausschnitt",
            }
        ]
    )

    assert "Retrieval-Details (1 Treffer)" in rendered
    assert "altbestand.pdf" in rendered
    assert "Historischer Retrieval-Ausschnitt" in rendered
    assert "Chunk" not in rendered
