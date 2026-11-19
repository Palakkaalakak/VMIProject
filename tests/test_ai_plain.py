from vmi.ai_helper import plain


def test_bold_italic_code_and_headings_are_stripped():
    raw = "## Verdict\n**Moat at first sight:** Wide. *Really* strong, see `ROIC`.\n* first\n* second\n__x__"
    assert plain(raw) == "Verdict\nMoat at first sight: Wide. Really strong, see ROIC.\n- first\n- second\nx"


def test_numbers_and_math_are_left_alone():
    raw = "1. Check margins (68% vs 66%)\n2. Growth 5*3 stays"
    assert plain(raw) == raw


def test_plain_text_unchanged():
    assert plain("Wide moat.\nNo doubts.") == "Wide moat.\nNo doubts."
