from agentaudit.htmltext import html_to_text


def test_converts_headings_lists_links_and_drops_scripts():
    html = """<h2>Lost your device?</h2><p>Use a <strong>backup code</strong>.</p>
    <ol><li>Open <a href="https://status.example.com">status</a></li><li>Sign in</li></ol>
    <ul><li>Members ask an owner</li></ul><script>track()</script><p>Fees &amp; credits</p>"""
    text = html_to_text(html)
    assert "## Lost your device?" in text
    assert "Use a **backup code**." in text
    assert "1. Open status (https://status.example.com)" in text
    assert "2. Sign in" in text
    assert "- Members ask an owner" in text
    assert "track()" not in text
    assert "Fees & credits" in text


def test_empty_input():
    assert html_to_text("") == ""
