"""Tests for Pillar 3 key metrics. Parser cases use word positions measured in the real
reports; data tests check the committed metrics file against itself and the PDFs."""

import hashlib
import json

import httpx
import pytest

from finsight import pillar3
from finsight.pillar3 import KM1_ROWS, Pillar3Error, Report


def word(text: str, x1: float, top: float) -> dict:
    return {"text": text, "x0": x1 - 5 * len(text), "x1": x1, "top": top}


def line(top: float, *parts: tuple[str, float]) -> list[dict]:
    return [word(text, x1, top) for text, x1 in parts]


# MSEHSE 2023 KM1 (page 6): five quarter columns, but rows only fill three of them.
HEADER_2023 = line(
    115,
    ("MSEHSE", 120),
    ("Group1", 150),
    ("Q4’23", 394.6),
    ("Q3’23", 429.8),
    ("Q2’23", 465.1),
    ("Q1’23", 500.3),
    ("Q4’22", 535.6),
)
CET1_ROW_2023 = line(
    137.9,
    ("1", 80),
    ("Common", 120),
    ("Equity", 150),
    ("Tier", 170),
    ("1", 175),
    ("(CET1)", 200),
    ("capital", 230),
    ("6,355", 394.6),
    ("6,192", 465.1),
    ("5,191", 535.6),
)


def test_values_go_to_the_column_they_line_up_with() -> None:
    _, columns = pillar3.parse_header(HEADER_2023)
    label, values = pillar3.split_row(CET1_ROW_2023)

    pairs = pillar3.assign_columns(values, columns)

    assert label == "1 Common Equity Tier 1 (CET1) capital"
    # In plain text the middle value looks like Q3'23; its position says Q2'23.
    assert [(period, w["text"]) for period, w in pairs] == [
        ("2023-12-31", "6,355"),
        ("2023-06-30", "6,192"),
        ("2022-12-31", "5,191"),
    ]


def test_a_value_between_columns_is_an_error_not_a_guess() -> None:
    _, columns = pillar3.parse_header(HEADER_2023)

    with pytest.raises(Pillar3Error, match="lines up with no column"):
        pillar3.assign_columns([word("6,192", 447.0, 137.9)], columns)


def test_header_footnote_markers_are_ignored() -> None:
    # MSI 2022: "MSI Group1 2 3" (footnotes as separate words); MSEHSE 2022: "Q4’213".
    header = line(
        100,
        ("MSI", 90),
        ("Group1", 97),
        ("2", 100),
        ("3", 103.6),
        ("Q4’22", 383.6),
        ("Q4’213", 530.7),
    )

    entity, columns = pillar3.parse_header(header)

    assert entity == "MSI Group"
    # The whole header cell is right-aligned, so values line up with the footnote's edge.
    assert columns == [("2022-12-31", 383.6), ("2021-12-31", 530.7)]


def test_lines_without_an_entity_before_the_periods_are_not_headers() -> None:
    assert pillar3.parse_header(line(100, ("Q4’23", 300), ("Q4'22", 340))) is None
    assert pillar3.parse_header(line(100, ("€MM", 60), ("a", 390), ("b", 425))) is None


def test_km1_row_with_an_unexpected_label_fails_loudly() -> None:
    with pytest.raises(Pillar3Error, match="row 5"):
        pillar3.row_metric("EU KM1", "5 Liquidity coverage ratio (%)")


def test_rows_are_matched_by_number_in_km1_and_by_label_in_tlac() -> None:
    assert pillar3.row_metric("UK KM1", "4 Total risk-weighted exposure amount") == "rwa"
    assert pillar3.row_metric("EU KM1", "EU 7a Additional own funds requirements") is None
    assert pillar3.row_metric("TLAC Key Metrics", "TLAC available") == "tlac_available"
    assert (
        pillar3.row_metric("TLAC Key Metrics", "Total Loss Absorbing Capacity (TLAC) available")
        == "tlac_available"
    )
    assert (
        pillar3.row_metric("TLAC Key Metrics", "TLAC at a percentage of leverage ratio exposures")
        == "tlac_ratio_leverage"
    )


@pytest.mark.parametrize(
    ("text", "value"), [("6,355", 6355), ("23.29%", 23.29), ("(1,234)", -1234), ("-", None)]
)
def test_parse_value(text: str, value: float | None) -> None:
    assert pillar3.parse_value(text) == value


# ---------- whole report: pages of words -> metrics ----------

REPORT = Report("Test Group", 2023, "test.pdf", "0" * 64, "EUR", ("MSESE Consol",))


def km1_page(entity: str, title: bool = True, value: str = "5,998") -> list[dict]:
    """One KM1 page with every kept row: one quarter column at x1=535.6."""
    lines = (
        [
            line(
                60,
                ("Table", 40),
                ("1:", 50),
                ("Key", 70),
                ("metrics", 100),
                ("(EU", 115),
                ("KM1)", 135),
            )
        ]
        if title
        else []
    )
    lines.append(
        line(80, *[(w, 60 + 30 * i) for i, w in enumerate(entity.split())], ("Q4’23", 535.6))
    )
    for i, (number, (_, label)) in enumerate(KM1_ROWS.items()):
        lines.append(line(100 + 12 * i, (number, 80), (label, 300), (value, 535.6)))
    return [w for ln in lines for w in ln]


def test_reads_a_table_that_continues_on_the_next_page_without_its_title() -> None:
    # MSEHSE 2023: the title is on page 6, MSESE Consol's columns on page 8.
    narrative = line(100, ("ratio", 200), ("increased", 260), ("by", 280), ("1.77%", 320))
    pages = [km1_page("MSEHSE Group1"), narrative, km1_page("MSESE Consol1 2", title=False)]

    metrics = pillar3.read_report(REPORT, pages)

    assert {m.entity for m in metrics} == {"MSESE Consol"}
    cet1 = next(m for m in metrics if m.metric == "cet1_capital")
    assert (cet1.value, cet1.unit, cet1.page, cet1.table) == (5998, "EUR millions", 3, "EU KM1")


def test_other_entities_figures_are_skipped() -> None:
    # MSI 2023 repeats MSESE Consol's KM1 in USD; MSESE Consol is read from its own report.
    pages = [km1_page("MSESE Consol"), km1_page("MSI Group", value="9,999")]

    metrics = pillar3.read_report(REPORT, pages)

    assert {m.as_printed for m in metrics} == {"5,998"}


def test_a_report_missing_a_metric_fails() -> None:
    page = [w for w in km1_page("MSESE Consol") if w["text"] not in ("14", "Leverage ratio")]

    with pytest.raises(Pillar3Error, match="no leverage_ratio for MSESE Consol"):
        pillar3.read_report(REPORT, [page])


# ---------- download: pinned hashes ----------


def test_download_checks_the_pinned_hash(tmp_path) -> None:
    content = b"%PDF-1.7 report"
    report = Report("G", 2023, "r.pdf", hashlib.sha256(content).hexdigest(), "EUR", ())
    calls = []

    def server(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, content=content)

    http = httpx.Client(transport=httpx.MockTransport(server))

    assert pillar3.download(report, http, tmp_path).read_bytes() == content
    pillar3.download(report, http, tmp_path)  # second time: from disk
    assert len(calls) == 1


def test_download_rejects_a_changed_report(tmp_path) -> None:
    report = Report("G", 2023, "r.pdf", "0" * 64, "EUR", ())
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))

    with pytest.raises(Pillar3Error, match="report changed"):
        pillar3.download(report, http, tmp_path)
    assert not (tmp_path / "r.pdf").exists()


# ---------- the committed metrics file ----------

DATA = json.loads(pillar3.METRICS_FILE.read_text())["metrics"]  # also proves it is valid JSON
BY_KEY = {(m["report_year"], m["entity"], m["metric"], m["period"]): m for m in DATA}


@pytest.mark.parametrize(
    ("key", "as_printed", "page"),
    [  # checked by hand against the PDFs
        ((2023, "MSEHSE Group", "cet1_capital", "2023-06-30"), "6,192", 6),
        ((2023, "MSEHSE Group", "cet1_ratio", "2023-12-31"), "23.29%", 6),
        ((2023, "MSEHSE Group", "tlac_available", "2023-12-31"), "9,255", 27),
        ((2023, "MSESE Consol", "rwa", "2023-12-31"), "27,066", 8),
        ((2023, "MSI Group", "rwa", "2023-12-31"), "155,523", 6),
        ((2023, "MSI Group", "tlac_ratio_rwa", "2023-12-31"), "29.12%", 27),
        ((2022, "MSEHSE Group", "rwa", "2021-12-31"), "21,221", 6),
        ((2022, "MSI Group", "cet1_capital", "2022-12-31"), "23,038", 6),
    ],
)
def test_metrics_file_matches_values_checked_in_the_pdfs(key, as_printed, page) -> None:
    assert (BY_KEY[key]["as_printed"], BY_KEY[key]["page"]) == (as_printed, page)


def test_no_values_for_quarters_left_blank() -> None:
    # MSEHSE 2023 KM1 has no Q3'23 or Q1'23 figures.
    assert (2023, "MSEHSE Group", "cet1_capital", "2023-09-30") not in BY_KEY


def test_comparatives_match_the_previous_years_report() -> None:
    # Each report repeats last year's Q4: a column mix-up would show up as a difference.
    pairs = [
        (m, BY_KEY[(y - 1, *rest)]) for (y, *rest), m in BY_KEY.items() if (y - 1, *rest) in BY_KEY
    ]

    assert len(pairs) >= 30
    assert all(a["value"] == b["value"] for a, b in pairs)


@pytest.mark.parametrize(
    ("ratio", "numerator", "denominator"),
    [
        ("cet1_ratio", "cet1_capital", "rwa"),
        ("tier1_ratio", "tier1_capital", "rwa"),
        ("total_capital_ratio", "total_capital", "rwa"),
        ("leverage_ratio", "tier1_capital", "leverage_exposure"),
        ("tlac_ratio_rwa", "tlac_available", "rwa"),
    ],
)
def test_printed_ratios_match_the_amounts(ratio, numerator, denominator) -> None:
    checked = 0
    for (year, entity, metric, period), m in BY_KEY.items():
        num = BY_KEY.get((year, entity, numerator, period))
        den = BY_KEY.get((year, entity, denominator, period))
        if metric == ratio and num and den:
            assert m["value"] == pytest.approx(100 * num["value"] / den["value"], abs=0.06)
            checked += 1
    assert checked >= 10


# ---------- lookup ----------


def test_key_metrics_for_a_year_come_from_that_years_report() -> None:
    result = pillar3.key_metrics("MSEHSE Group", 2023)

    assert result["source"]["report"].endswith("31 December 2023")
    cet1 = result["metrics"]["cet1_ratio"]
    assert cet1["unit"] == "%"
    assert [v["period"] for v in cet1["values"]] == ["2023-12-31", "2023-06-30"]
    assert cet1["values"][0] == {
        "period": "2023-12-31",
        "value": 23.29,
        "as_printed": "23.29%",
        "table": "EU KM1",
        "page": 6,
    }


def test_key_metrics_for_an_unknown_year_lists_what_is_available() -> None:
    with pytest.raises(Pillar3Error, match="MSI Group 2022, 2023"):
        pillar3.key_metrics("MSI Group", 2019)


# ---------- report text for the Knowledge Base ----------


def test_report_pages_keep_the_body_with_its_chapters() -> None:
    texts = [
        "Pillar 3 Regulatory Disclosure (UK)\nMorgan Stanley International",  # cover
        "Pillar 3 Regulatory Disclosure (UK): Index\nTable 1 ..... 6",
        "Pillar 3 Regulatory Disclosure (EU): 1. Overview and Key Metrics\nThe MSI Group...\n"
        "Page | 3",
        "Table 40 (continued) NSFR\n$MM a b",  # a table page without the running header
        "Pillar 3 Regulatory Disclosure (UK): Leverage\nThe leverage ratio fell.\nPage | 5",
        "Pillar 3 Regulatory Disclosure (UK): Appendix I: Board of Directors\nNames",
        "Pillar 3 Regulatory Disclosure (UK): Abbreviations\nAT1 Additional Tier 1",
    ]

    pages = pillar3.report_pages(texts)

    assert [(p.number, p.chapter) for p in pages] == [
        (3, "Overview and Key Metrics"),  # numbering removed
        (4, "Overview and Key Metrics"),  # inherits the chapter before
        (5, "Leverage"),
    ]  # stops at the first appendix
    assert pages[2].text == "The leverage ratio fell."  # running header and footer removed
