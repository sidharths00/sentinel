# tests/test_cli.py
import pytest
from click.testing import CliRunner


def test_cli_help():
    from sentinel.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "audit" in result.output.lower()


def test_cli_audit_no_entries(tmp_path):
    from sentinel.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--db", str(tmp_path / "test.db")])
    assert result.exit_code == 0
    # Either "No entries" message or empty/clean output
    assert result.exception is None


def test_cli_audit_help():
    from sentinel.cli import cli
    runner = CliRunner()
    result = runner.invoke(cli, ["audit", "--help"])
    assert result.exit_code == 0
    assert "--agent-id" in result.output or "agent" in result.output.lower()
