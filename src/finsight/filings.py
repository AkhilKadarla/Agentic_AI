"""Extract the narrative sections (Risk Factors, MD&A) from a company's latest 10-K.

A 10-K is one long HTML document. We turn it into plain text and cut out two sections:
  - Item 1A  Risk Factors: what could go wrong, in the company's own words
  - Item 7   MD&A (Management's Discussion and Analysis): management explains the results

Real filings are messy, and each rule below exists because a real 10-K needed it:
  - section names also appear in the table of contents and in cross-references, so we
    skip those and use the heading nearest to the section's end (Costco, Microsoft)
  - styling can split words ("RIS K FACTORS" in Microsoft's 10-K), so headings allow
    spaces between letters
  - some companies publish MD&A in a separate annual-report exhibit and the 10-K only
    points to it (JPMorgan); very short sections are reported as not found
"""

import re
import warnings
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from finsight import sec

# 10-Ks are inline-XBRL (XHTML); the HTML parser reads them fine.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

MIN_SECTION_CHARS = 5000  # shorter = only a cross-reference to another document


def _loose(words: str) -> str:
    """Regex for `words` that tolerates spaces inside words ("RIS K FACTORS")."""
    return r"\s+".join(r"\s?".join(re.escape(ch) for ch in word) for word in words.split())


SEP = r"\.?\s*[-–—:.]?\s*"  # between "Item 1A" and its title: ". ", "—", " - ", ": "
SECTIONS = {
    "risk_factors": (
        "Risk Factors",
        rf"item\s*1a{SEP}{_loose('risk factors')}",
        rf"item\s*1b{SEP}|item\s*1c{SEP}|item\s*2{SEP}{_loose('properties')}",
    ),
    "mdna": (
        "Management's Discussion and Analysis (MD&A)",
        rf"item\s*7{SEP}{_loose('management')}.{{0,3}}s?\s*{_loose('discussion')}",
        rf"item\s*7a{SEP}|item\s*8{SEP}{_loose('financial statements')}",
    ),
}

_CROSS_REFERENCE = re.compile(r"^\s*[”\"']")  # heading text inside quotes
_TABLE_OF_CONTENTS = re.compile(r"item\s*\d", re.I)  # another "Item N" right after it


@dataclass
class Section:
    name: str  # "risk_factors" or "mdna"
    title: str
    text: str


@dataclass
class Filing10K:
    ticker: str
    company: str
    report_date: str  # fiscal year end, e.g. "2025-09-27"
    filing_date: str
    url: str
    sections: list[Section]
    missing: list[str]  # section titles that could not be extracted


def html_to_text(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ")).strip()


def extract_section(text: str, start: str, end: str) -> str:
    """The longest span from a real section heading to the next section's heading."""
    starts = [
        m
        for m in re.finditer(start, text, re.I)
        if not _CROSS_REFERENCE.match(text[m.end() : m.end() + 3])
        and not _TABLE_OF_CONTENTS.search(text[m.end() : m.end() + 60])
    ]
    best = ""
    for end_match in re.finditer(end, text, re.I):
        before = [m for m in starts if m.end() <= end_match.start()]
        if before:
            span = text[before[-1].start() : end_match.start()].strip()
            if len(span) > len(best):
                best = span
    return best


def latest_10k(ticker: str, http: httpx.Client) -> Filing10K:
    """Download a company's most recent 10-K and extract its narrative sections."""
    recent = sec.get_recent_filings(ticker, http, form_type="10-K", limit=1)
    if not recent["filings"]:
        raise sec.CompanyNotFoundError(f"{recent['company']} has no 10-K filings on EDGAR")
    filing = recent["filings"][0]
    response = http.get(filing["url"])
    response.raise_for_status()
    text = html_to_text(response.text)

    sections, missing = [], []
    for name, (title, start, end) in SECTIONS.items():
        body = extract_section(text, start, end)
        if len(body) >= MIN_SECTION_CHARS:
            sections.append(Section(name, title, body))
        else:
            missing.append(title)
    return Filing10K(
        ticker=recent["ticker"],
        company=recent["company"],
        report_date=filing["report_date"],
        filing_date=filing["filing_date"],
        url=filing["url"],
        sections=sections,
        missing=missing,
    )
