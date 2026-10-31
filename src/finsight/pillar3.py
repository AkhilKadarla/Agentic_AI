"""Key metrics from Morgan Stanley's public Pillar 3 disclosure reports (PDF).

Banks publish Pillar 3 reports so that anyone can check their capital strength. Each report
opens with a Key Metrics table (KM1: capital, risk-weighted assets, capital ratios, leverage
ratio) for the last five quarters; TLAC (loss-absorbing capacity) has a small table of its own.

  build  : download the PDFs (checked against pinned SHA-256 hashes) -> read the tables
           -> src/finsight/data/pillar3_key_metrics.json, reviewed in git like code
  lookup : the get_key_metrics tool reads that file - no PDF parsing at question time
  text   : report_pages() gives each body page's text and chapter, for the Knowledge Base
           (knowledge_base.upload_report_pages): passages for "why" questions, cited by page

Tables are read by word *position*, not as plain text. Each rule comes from a real report:
  - rows can leave quarters blank and plain text silently drops the gaps (MSEHSE 2023 KM1:
    3 values under 5 quarters - the middle one is Q2'23, not Q3'23). Numbers are
    right-aligned, so a value belongs to the header whose right edge it lines up with;
    a value that lines up with no header is an error, never a guess
  - footnote markers stick to labels ("MSEHSE Group1", "Q4’213"), apostrophes vary
  - a table can continue on the next page without its title (MSIP's KM1, MSI 2023 p7)
  - a parent's report repeats a subsidiary's figures in another currency (MSESE Consol in
    USD in MSI 2023), so each entity is read only from its own report
  - TLAC rows have no row numbers, so they are matched by label
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path

import httpx

BASE_URL = "https://www.morganstanley.com/content/dam/msdotcom/en/about-us-ir/pillar3/"
REPORTS_DIR = Path("data/reg_reports")  # downloaded PDFs (git-ignored)
METRICS_FILE = Path(__file__).parent / "data" / "pillar3_key_metrics.json"


class Pillar3Error(RuntimeError):
    pass


@dataclass(frozen=True)
class Report:
    group: str  # whose report it is
    year: int  # figures as at 31 December of this year
    filename: str
    sha256: str  # pinned: a re-published file must be reviewed before we use it
    currency: str
    entities: tuple[str, ...]  # entities whose figures we read from this report

    @property
    def url(self) -> str:
        return BASE_URL + self.filename

    @property
    def title(self) -> str:
        return f"{self.group} Pillar 3 Disclosure Report, 31 December {self.year}"


ENTITIES = {
    "MSEHSE Group": "Morgan Stanley Europe Holding SE and its subsidiaries (EU; euros)",
    "MSESE Consol": "Morgan Stanley Europe SE, consolidated (EU; euros; reported from 2023)",
    "MSI Group": "Morgan Stanley International Limited and its subsidiaries (UK; US dollars)",
    "MSIP": "Morgan Stanley & Co. International plc (UK; US dollars)",
}

REPORTS = [
    Report(
        "MSEHSE Group",
        2022,
        "MSEHSE_Pillar_3_Disclosure_Report_31_December_2022_English.pdf",
        "8c1be33f890afb4114a03c21a43b3d1530380a31de08c9968343448f002d0175",
        "EUR",
        ("MSEHSE Group",),
    ),
    Report(
        "MSEHSE Group",
        2023,
        "MSEHSE_Pillar_3_Disclosure_Report_31_December_2023_English.pdf",
        "859969f03265b98cc490dd75bae0b5ca85e789511572c8996067bf0e363a91e8",
        "EUR",
        ("MSEHSE Group", "MSESE Consol"),
    ),
    Report(
        "MSI Group",
        2022,
        "2022_Pillar_3_Disclosures_Morgan_Stanley_International_Limited.pdf",
        "0347dec56089a1ba15a866dc5829261acd03f63ab12b66fc782e154f6b123adb",
        "USD",
        ("MSI Group", "MSIP"),
    ),
    Report(
        "MSI Group",
        2023,
        "2023_Pillar_3_Disclosures_Morgan_Stanley_International_Limited.pdf",
        "8f1a654497feeda4273a5905d47956560af56bfb4c7bf51ea2c66086a6ae01ed",
        "USD",
        ("MSI Group", "MSIP"),
    ),
]

METRICS = {
    "cet1_capital": "Common Equity Tier 1 (CET1) capital",
    "tier1_capital": "Tier 1 capital",
    "total_capital": "Total capital (own funds)",
    "rwa": "Total risk-weighted exposure amount (RWAs)",
    "cet1_ratio": "CET1 ratio",
    "tier1_ratio": "Tier 1 ratio",
    "total_capital_ratio": "Total capital ratio",
    "leverage_exposure": "Leverage ratio total exposure measure",
    "leverage_ratio": "Leverage ratio",
    "tlac_available": "TLAC available",
    "tlac_ratio_rwa": "TLAC as a percentage of RWAs",
    "tlac_ratio_leverage": "TLAC as a percentage of the leverage exposure measure",
}

# KM1 rows we keep: row number -> (metric, words its label must contain). The label check
# makes a changed template fail loudly instead of filing a number under the wrong metric.
KM1_ROWS = {
    "1": ("cet1_capital", "Common Equity Tier 1"),
    "2": ("tier1_capital", "Tier 1"),
    "3": ("total_capital", "Total capital"),
    "4": ("rwa", "exposure amount"),
    "5": ("cet1_ratio", "Common Equity Tier 1 ratio"),
    "6": ("tier1_ratio", "Tier 1 ratio"),
    "7": ("total_capital_ratio", "Total capital ratio"),
    "13": ("leverage_exposure", "exposure measure"),
    "14": ("leverage_ratio", "Leverage ratio"),
}
TLAC_ROWS = [
    (re.compile(r"available$"), "tlac_available"),
    (re.compile(r"^TLAC as a percentage of RWA"), "tlac_ratio_rwa"),
    (re.compile(r"^TLAC a[st] a percentage of leverage"), "tlac_ratio_leverage"),
]
TLAC_ENTITIES = ("MSEHSE Group", "MSI Group")  # the groups subject to TLAC

TITLE = re.compile(r"^Table \w+:")
PERIOD = re.compile(r"^Q([1-4])['’](\d{2})\d?$")  # a trailing digit is a footnote marker
VALUE = re.compile(r"^(-|\(?-?[\d,]+(\.\d+)?%?\)?)$")
QUARTER_END = {"1": "03-31", "2": "06-30", "3": "09-30", "4": "12-31"}
LINE_TOLERANCE = 3.0  # points: words this close vertically are on the same line
ALIGN_TOLERANCE = 3.0  # points: a value's right edge vs its header's (columns are ~35 apart)


@dataclass
class KeyMetric:
    entity: str
    metric: str
    period: str  # quarter end, e.g. "2023-12-31"
    value: float  # millions of `unit` currency, or a percentage
    unit: str  # "%", "EUR millions" or "USD millions"
    as_printed: str  # exactly as in the report, e.g. "23.29%"
    table: str  # "EU KM1", "UK KM1" or "TLAC Key Metrics"
    page: int
    report: str
    report_year: int


# ---------- build: PDF -> key metrics ----------


def group_lines(words: list[dict]) -> list[list[dict]]:
    """pdfplumber words (text, x0, x1, top) -> lines, top to bottom, each left to right."""
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - word["top"]) <= LINE_TOLERANCE:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def parse_header(line: list[dict]) -> tuple[str, list[tuple[str, float]]] | None:
    """'MSI Group1 Q4'23 Q3'23 ...' -> ("MSI Group", [("2023-12-31", right edge), ...])."""
    first = next((i for i, w in enumerate(line) if PERIOD.match(w["text"])), None)
    if not first:  # no periods, or no entity name before them
        return None
    columns = []
    for word in line[first:]:
        match = PERIOD.match(word["text"])
        if not match:
            return None
        quarter, year = match.groups()
        # The whole header cell is right-aligned, footnote included ("Q4’213" in MSEHSE
        # 2022): its values line up with the word's full right edge.
        columns.append((f"20{year}-{QUARTER_END[quarter]}", word["x1"]))
    # Footnote markers can be part of the last word or words of their own ("MSI Group1 2 3")
    entity = re.sub(r"[\d\s]+$", "", " ".join(w["text"] for w in line[:first]))
    return entity, columns


def split_row(line: list[dict]) -> tuple[str, list[dict]]:
    """A row's label and its values (the run of number-like words at the end of the line)."""
    i = len(line)
    while i > 0 and VALUE.match(line[i - 1]["text"]):
        i -= 1
    return " ".join(w["text"] for w in line[:i]), line[i:]


def assign_columns(values: list[dict], columns: list[tuple[str, float]]) -> list[tuple[str, dict]]:
    """Pair each value with the column header its right edge lines up with."""
    pairs = []
    for word in values:
        period, x1 = min(columns, key=lambda c: abs(c[1] - word["x1"]))
        if abs(x1 - word["x1"]) > ALIGN_TOLERANCE:
            raise Pillar3Error(
                f"'{word['text']}' (right edge {word['x1']:.1f}) lines up with no column"
            )
        if period in (p for p, _ in pairs):
            raise Pillar3Error(f"Two values in the {period} column of one row")
        pairs.append((period, word))
    return pairs


def row_metric(table: str, label: str) -> str | None:
    """Which metric a row holds, or None for rows we don't keep."""
    if table == "TLAC Key Metrics":
        return next((metric for pattern, metric in TLAC_ROWS if pattern.search(label)), None)
    number, _, name = label.partition(" ")
    if number not in KM1_ROWS:
        return None
    metric, expected = KM1_ROWS[number]
    if expected not in name:
        raise Pillar3Error(f"{table} row {number} is '{name}', expected '{expected}'")
    return metric


def parse_value(text: str) -> float | None:
    if text == "-":  # not applicable
        return None
    number = float(text.strip("()-%").replace(",", ""))
    return -number if text.startswith(("(", "-")) else number


def table_name(title: str) -> str | None:
    # "Key metrics" in most reports, "Key Metrics" in MSI 2022
    if km1 := re.search(r"Key metrics \((EU|UK) KM1\)", title, re.I):
        return f"{km1.group(1)} KM1"
    return "TLAC Key Metrics" if "TLAC Key Metrics" in title else None


def read_report(report: Report, pages: list[list[dict]]) -> list[KeyMetric]:
    """The key metrics in one report, given the words on each page."""
    found: dict[tuple[str, str, str], KeyMetric] = {}
    table = None  # the table we are in, set by its title; it may continue on the next page
    for page_number, words in enumerate(pages, start=1):
        entity = columns = None  # every page repeats the column headers
        for line in group_lines(words):
            text = " ".join(w["text"] for w in line)
            if TITLE.match(text):
                table, entity, columns = table_name(text), None, None
                continue
            if table is None:
                continue
            if header := parse_header(line):
                entity, columns = header if header[0] in report.entities else (None, None)
                continue
            if columns is None:
                continue
            label, values = split_row(line)
            metric = row_metric(table, label) if values else None
            if metric is None:
                continue
            for period, word in assign_columns(values, columns):
                value = parse_value(word["text"])
                if value is None:
                    continue
                key = (entity, metric, period)
                if key in found:
                    raise Pillar3Error(f"{report.title}: {key} appears twice")
                found[key] = KeyMetric(
                    entity=entity,
                    metric=metric,
                    period=period,
                    value=value,
                    unit="%" if word["text"].endswith("%") else f"{report.currency} millions",
                    as_printed=word["text"],
                    table=table,
                    page=page_number,
                    report=report.title,
                    report_year=report.year,
                )
    check_complete(report, found)
    return list(found.values())


def check_complete(report: Report, found: dict) -> None:
    """Every entity must have every metric at the report date - or the parser missed a row."""
    year_end = f"{report.year}-12-31"
    for entity in report.entities:
        expected = [m for m, _ in KM1_ROWS.values()]
        if entity in TLAC_ENTITIES:
            expected += [m for _, m in TLAC_ROWS]
        missing = [m for m in expected if (entity, m, year_end) not in found]
        if missing:
            raise Pillar3Error(f"{report.title}: no {', '.join(missing)} for {entity}")


def download(report: Report, http: httpx.Client, folder: Path = REPORTS_DIR) -> Path:
    """The report's PDF, downloaded once and always checked against its pinned hash."""
    path = folder / report.filename
    if path.exists():
        content = path.read_bytes()
    else:
        response = http.get(report.url)
        response.raise_for_status()
        content = response.content
    digest = hashlib.sha256(content).hexdigest()
    if digest != report.sha256:
        raise Pillar3Error(
            f"{report.filename} has SHA-256 {digest[:12]}..., expected {report.sha256[:12]}... "
            "- the published report changed: review it, then update REPORTS"
        )
    folder.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def page_words(path: Path) -> list[list[dict]]:
    import pdfplumber  # only needed to build the metrics file (the `reports` dependency group)

    with pdfplumber.open(path) as pdf:
        return [page.extract_words() for page in pdf.pages]


# Every body page starts with "Pillar 3 Regulatory Disclosure (UK): <chapter>"; pages that
# are one big table don't, and belong to the chapter before. The chapter is sometimes
# numbered ("1. Overview and Key Metrics", MSEHSE 2022).
RUNNING_HEADER = re.compile(r"^Pillar 3 Regulatory Disclosure \((?:EU|UK)\)(?::\s*(.*))?$")
FOOTER = re.compile(r"^Page \| \d+$")


@dataclass
class ReportPage:
    number: int
    chapter: str
    text: str


def report_pages(texts: list[str]) -> list[ReportPage]:
    """The body of a report, page by page with its chapter: from the first chapter after the
    index up to the first appendix (templates, CRR mapping tables, abbreviations, and in MSI
    2023 the financial statements - mostly noise for a search by meaning)."""
    pages, chapter = [], None
    for number, text in enumerate(texts, start=1):
        lines = text.splitlines()
        header = RUNNING_HEADER.match(lines[0]) if lines else None
        if header:
            chapter = re.sub(r"^\d+\.\s*", "", header.group(1) or "").strip() or None
            lines = lines[1:]
        if chapter and chapter.startswith("Appendix"):
            break
        if chapter in (None, "Index"):  # the cover page and the table of contents
            continue
        body = "\n".join(line for line in lines if not FOOTER.match(line)).strip()
        if body:
            pages.append(ReportPage(number, chapter, body))
    return pages


def page_texts(path: Path) -> list[str]:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def build(http: httpx.Client, folder: Path = REPORTS_DIR, out: Path = METRICS_FILE) -> int:
    """Download every report, read its key metrics and write the metrics file."""
    metrics = []
    for report in REPORTS:
        metrics += read_report(report, page_words(download(report, http, folder)))
    reports = [
        {"report": r.title, "url": r.url, "sha256": r.sha256, "currency": r.currency}
        for r in REPORTS
    ]
    # One value per line, so a changed number is a one-line diff in review.
    rows = ",\n  ".join(json.dumps(asdict(m)) for m in metrics)
    reports_json = json.dumps(reports, indent=2).replace("\n", "\n  ")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f'{{\n "reports": {reports_json},\n "metrics": [\n  {rows}\n ]\n}}\n')
    return len(metrics)


# ---------- lookup: what the agent's tool calls ----------


@cache
def load(path: Path = METRICS_FILE) -> dict:
    if not path.exists():
        raise Pillar3Error(f"{path} is missing - build it with: finsight pillar3")
    return json.loads(path.read_text())


def available(path: Path = METRICS_FILE) -> dict[str, list[int]]:
    """{entity: [report years]} - what get_key_metrics can answer."""
    years: dict[str, set[int]] = {}
    for m in load(path)["metrics"]:
        years.setdefault(m["entity"], set()).add(m["report_year"])
    return {entity: sorted(y) for entity, y in years.items()}


def key_metrics(entity: str, year: int, path: Path = METRICS_FILE) -> dict:
    """An entity's key metrics for the quarters of `year`, from that year's annual report."""
    data = load(path)
    rows = [
        m
        for m in data["metrics"]
        if m["entity"] == entity and m["report_year"] == year and m["period"].startswith(str(year))
    ]
    if not rows:
        have = "; ".join(f"{e} {', '.join(map(str, y))}" for e, y in available(path).items())
        raise Pillar3Error(f"No key metrics for {entity} in {year}. Available: {have}")
    metrics: dict[str, dict] = {}
    for m in sorted(rows, key=lambda m: m["period"], reverse=True):
        entry = metrics.setdefault(
            m["metric"], {"name": METRICS[m["metric"]], "unit": m["unit"], "values": []}
        )
        entry["values"].append(
            {key: m[key] for key in ("period", "value", "as_printed", "table", "page")}
        )
    return {
        "entity": entity,
        "description": ENTITIES[entity],
        "year": year,
        "source": next(
            {"report": r["report"], "url": r["url"]}
            for r in data["reports"]
            if r["report"] == rows[0]["report"]
        ),
        "metrics": {name: metrics[name] for name in METRICS if name in metrics},
    }
