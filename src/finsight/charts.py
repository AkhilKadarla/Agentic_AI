"""Charts for research notes (Altair, rendered by the Streamlit UI).

One small chart per metric ("small multiples"): revenue in billions and a margin in
percent can never share an axis, so each metric gets its own. Companies keep the same
color in every chart, assigned in a fixed order.
"""

import altair as alt

from finsight.notes import ResearchNote

# Categorical slots 1-4 of a validated colorblind-safe palette, always used in this order.
COMPANY_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]


def chart_rows(note: ResearchNote) -> dict[str, list[dict]]:
    """Group a note's metrics by name, keeping metrics with at least two data points."""
    groups: dict[str, list[dict]] = {}
    for m in note.key_metrics:
        groups.setdefault(m.name, []).append(
            {
                "company": m.company,
                "period": m.period,
                "value": m.value / 1e9 if m.unit == "USD" else m.value,
                "unit": display_unit(m.unit),
            }
        )
    return {name: rows for name, rows in groups.items() if len(rows) >= 2}


def display_unit(unit: str) -> str:
    if unit == "USD":
        return "$B"  # dollar amounts are charted in billions
    if unit.startswith("USD/"):
        return "$/share"
    return unit


def metric_chart(name: str, rows: list[dict], companies: list[str]) -> alt.Chart:
    unit = rows[0]["unit"]
    return (
        alt.Chart(alt.Data(values=rows), title=f"{name} ({unit})")
        .mark_bar(cornerRadiusEnd=4, size=14)
        .encode(
            x=alt.X("period:N", title=None, sort="ascending", axis=alt.Axis(labelAngle=0)),
            xOffset=alt.XOffset("company:N", sort=companies),
            y=alt.Y("value:Q", title=None, axis=alt.Axis(grid=True, gridOpacity=0.3)),
            color=alt.Color(
                "company:N",
                title="Company",
                scale=alt.Scale(domain=companies, range=COMPANY_COLORS[: len(companies)]),
                legend=alt.Legend(orient="top") if len(companies) > 1 else None,
            ),
            tooltip=[
                alt.Tooltip("company:N", title="Company"),
                alt.Tooltip("period:N", title="Period"),
                alt.Tooltip("value:Q", title=unit, format=",.2f"),
            ],
        )
        .properties(height=220)
    )
