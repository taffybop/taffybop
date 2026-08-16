from __future__ import annotations

from app.services.serializer import to_markdown


def test_serializer_preserves_structured_item_and_image_ocr_order() -> None:
    table_html = (
        "<table>\n"
        "  <tr><th>Field</th><th>Value</th></tr>\n"
        '  <tr><td colspan="2">Merged</td></tr>\n'
        "</table>"
    )
    result = {
        "pages": [
            {
                "items": [
                    {
                        "type": "heading",
                        "value": "Approval",
                        "level": 2,
                    },
                    {
                        "type": "image",
                        "ocr_text": (
                            "Signer Name: Ada Lovelace\n"
                            "Signing Reason: I approve this document"
                        ),
                    },
                    {
                        "type": "list",
                        "ordered": False,
                        "items": [
                            {"value": "Native text", "level": 0},
                            {"value": "Nested detail", "level": 1},
                        ],
                    },
                    {
                        "type": "table",
                        "html": table_html,
                        "md": "| lossy | fallback |",
                    },
                ]
            }
        ]
    }

    markdown = to_markdown(result)

    assert markdown == (
        "## Approval\n\n"
        "Signer Name: Ada Lovelace\n"
        "Signing Reason: I approve this document\n\n"
        "- Native text\n"
        "  - Nested detail\n\n"
        f"{table_html}\n"
    )
    assert markdown.index("## Approval") < markdown.index("Signer Name:")
    assert markdown.index("Signer Name:") < markdown.index("- Native text")
    assert markdown.index("- Native text") < markdown.index("<table>")
    assert "| lossy | fallback |" not in markdown


def test_serializer_renders_ordered_lists_and_nested_header_footer_items() -> None:
    result = {
        "pages": [
            {
                "items": [
                    {
                        "type": "header",
                        "items": [
                            {"value": "Document title"},
                            {"value": "Confidential"},
                        ],
                    },
                    {
                        "type": "heading",
                        "value": "Procedure",
                        "level": 99,
                    },
                    {
                        "type": "list",
                        "ordered": True,
                        "items": [
                            {"value": "First", "level": 0},
                            {"value": "Second", "level": 0},
                        ],
                    },
                    {
                        "type": "footer",
                        "items": [{"value": "Page 1 of 1"}],
                    },
                ]
            }
        ]
    }

    assert to_markdown(result) == (
        "Document title\n\n"
        "Confidential\n\n"
        "###### Procedure\n\n"
        "1. First\n"
        "2. Second\n\n"
        "Page 1 of 1\n"
    )

