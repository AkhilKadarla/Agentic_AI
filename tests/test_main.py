"""Smoke tests: prove the package imports and the CLI entry point runs."""

import finsight


def test_version_is_set() -> None:
    assert finsight.__version__ == "0.1.0"


def test_main_prints_banner(capsys) -> None:
    finsight.main()
    output = capsys.readouterr().out
    assert "FinSight" in output
    assert finsight.__version__ in output
