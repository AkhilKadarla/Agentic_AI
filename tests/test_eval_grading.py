"""Sanity checks for the number-accuracy eval's grader (no API calls).

Before trusting any eval score: right answers must pass (oracle ~100%), empty answers and
plausible wrong answers must fail (null ~0%). A grader that fails these would make every
later number meaningless.
"""

import json
from pathlib import Path

import pytest

from evals.number_accuracy.grading import date_present, grade_numbers, numbers_in, value_present

CASES = [
    json.loads(line)
    for line in (Path(__file__).parents[1] / "evals/number_accuracy/cases.jsonl").open()
]
NUMBER_CASES = [c for c in CASES if not c["unavailable"]]


def say(e: dict, scale: float = 1.0) -> str:
    """Write an expected value the way a person would (optionally distorted by `scale`)."""
    if e["unit"] == "date":
        return e["value"]
    if e["unit"] == "%":
        return f"{e['value'] + (scale - 1) * 20:.1f}%"  # scale 1.05 -> one point off
    value = e["value"] * scale
    if e["unit"] == "USD" and abs(value) >= 1e9:
        return f"${value / 1e9:,.1f} billion"
    return f"${value:,.2f}"


def test_case_file_is_well_formed() -> None:
    assert len(CASES) == 25
    assert len({c["id"] for c in CASES}) == 25
    for c in NUMBER_CASES:
        assert c["expected"] and c["inputs"], c["id"]


@pytest.mark.parametrize("case", NUMBER_CASES, ids=lambda c: c["id"])
def test_oracle_answer_passes(case) -> None:
    answer = "Here are the figures: " + "; ".join(say(e) for e in case["expected"])
    tool_results = [json.dumps({"values": [i["value"] for i in case["inputs"]]})]

    result = grade_numbers(case, answer, tool_results)

    assert result["grade"] == {"correct": 1.0, "from_data": 1.0}, result["explanation"]


@pytest.mark.parametrize("case", NUMBER_CASES, ids=lambda c: c["id"])
def test_null_answer_fails(case) -> None:
    result = grade_numbers(case, "I don't know.", [])

    assert result["grade"] == {"correct": 0.0, "from_data": 0.0}


@pytest.mark.parametrize(
    "case", [c for c in NUMBER_CASES if c["expected"][0]["unit"] != "date"], ids=lambda c: c["id"]
)
def test_plausible_wrong_answer_fails(case) -> None:
    answer = "; ".join(say(e, scale=1.05) for e in case["expected"])  # 5% / 1 point off

    assert grade_numbers(case, answer, [])["grade"]["correct"] == 0.0


APPLE = {"value": 416_161_000_000, "unit": "USD", "tolerance": 0.01}


@pytest.mark.parametrize(
    "text",
    [
        "Revenue was $416.2 billion.",
        "Revenue: $416.16B",
        "Revenue of $416,161 million",
        "| Revenue | 416.2 |  (in $ billions)",
        "revenue of $416 billion",
    ],
)
def test_dollar_formats_that_should_match(text) -> None:
    assert value_present(APPLE, text)


@pytest.mark.parametrize(
    "text",
    ["Revenue was $391.0 billion.", "Revenue grew 416%", "No figures available."],
)
def test_dollar_texts_that_should_not_match(text) -> None:
    assert not value_present(APPLE, text)


def test_percent_tolerance_and_sign_words() -> None:
    growth = {"value": -2.93, "unit": "%", "tolerance": 0.25}

    assert value_present(growth, "Revenue fell 2.9% year over year")
    assert value_present(growth, "a change of -3.0%")
    assert not value_present(growth, "Revenue fell 3.5%")


def test_dates_in_several_forms() -> None:
    for text in ["filed on 2026-02-25", "on February 25, 2026", "Feb 25, 2026", "2/25/2026"]:
        assert date_present("2026-02-25", text), text
    assert not date_present("2026-02-25", "filed on February 26, 2026")


def test_numbers_in_reads_units() -> None:
    assert numbers_in("$4.42 trillion and 26.9% and 7.46") == [
        (4.42e12, "scaled"),
        (26.9, "%"),
        (7.46, "plain"),
    ]
