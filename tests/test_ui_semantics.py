import pandas as pd
from guanlan.ui.common import color_for, history_chart, fingerprint


def test_country_colors_do_not_depend_on_order_or_subset():
    frame = pd.DataFrame([{"country_code":c,"year":y,"value":y-2000} for c in ["CHN","USA","DEU"] for y in [2023,2024]])
    first = history_chart(frame,"走势","%",{"CHN":"中国","USA":"美国","DEU":"德国"})
    second = history_chart(frame.loc[frame.country_code!="CHN"],"走势","%",{"DEU":"德国","USA":"美国"})
    colors = {t.name:t.line.color for t in first.data}
    assert all(t.line.color==colors[t.name] for t in second.data)
    assert colors['美国（USA）'] == color_for('USA')


def test_brief_identity_changes_when_snapshot_or_report_parameters_change():
    facts = {"country":"CHN","year":2024,"sources":{"wdi":"hash-a"},"cohort":"全球"}
    assert fingerprint(facts) != fingerprint({**facts,"sources":{"wdi":"hash-b"}})
    assert fingerprint(facts) != fingerprint({**facts,"cohort":"同收入组"})
