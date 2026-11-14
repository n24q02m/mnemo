"""The `mnemo` console script must present itself by its installed name.

`mnemo` and `mnemo-pilot` map to the same entry point, but only `mnemo` is the
documented command. A hard-coded ``prog`` of ``mnemo-pilot`` made every usage
line, ``--help`` header and argument error talk about a program the reader was
never told to run.
"""

from __future__ import annotations

import pytest

from mnemo_cli.__main__ import main


def test_help_names_the_installed_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: mnemo ")
    assert "mnemo-pilot" not in out


def test_missing_command_error_names_the_installed_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])

    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("usage: mnemo ")
    assert "mnemo-pilot" not in err
    assert "the following arguments are required: command" in err


def test_version_flag_prints_the_installed_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mnemo import __version__

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out == f"mnemo {__version__}\n"
