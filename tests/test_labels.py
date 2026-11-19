from vmi import labels, settings


def test_every_rule_has_a_readable_title():
    for s in settings.schema():
        t = s["title"]
        assert t and "_" not in t, s["key"]
        assert s["section_title"]


def test_known_titles():
    assert labels.title("valuation.reit_pnav_max") == "REIT maximum price / NAV"
    assert labels.title("profitability.min_roe") == "Minimum ROE"
