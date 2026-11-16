from pathlib import Path

from server.fetch import html_to_text, quote_in_text

ROOT = Path(__file__).resolve().parents[1]


def test_quote_check_normalises_quotes_and_whitespace():
    text = "Vyntelligence’s deployments have   demonstrated that reducing field visits by 50%"
    assert quote_in_text("Vyntelligence's deployments have demonstrated", text)
    assert not quote_in_text("deployments have proven", text)


def test_quote_check_rejects_tiny_quotes():
    assert not quote_in_text("50%", "reducing field visits by 50%")


def test_extracts_paragraphs_from_html():
    sentence = "Reducing field visits by 50% saves approximately 4 million carbon miles annually. "
    html = (
        "<html><head><title>T</title></head><body>"
        "<nav>menu menu menu menu menu menu menu menu</nav>"
        f"<p>{sentence * 20}</p></body></html>"
    )
    title, text = html_to_text(html)
    assert title == "T"
    assert "4 million carbon miles" in text
    assert "menu" not in text
