from pathlib import Path
import importlib.util
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "open_source_bot_reference_check.py"
spec = importlib.util.spec_from_file_location("reference_check", SCRIPT)
reference_check = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference_check
spec.loader.exec_module(reference_check)


def write_doc(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def complete_doc_text():
    return """
# Open-Source Bot Plumbing Survey

Class 1 planning document.

This survey does not copy external code.

## Projects

Freqtrade
Hummingbot
Jesse
OctoBot
CCXT

## Patterns

Fill event is the source of truth
Immutable fill ledger
Stable cycle ID
Exchange connector boundary
Fee-aware realized P/L
Paper/backtest/live parity
Reconciliation before tuning

## Safety

Do not install or migrate.
Do not copy GPL code.
Do not copy public strategy logic.
Do not change live bot behavior.
Do not tune notional.

## Next

P2-010
P2-011
P2-012
"""


def test_missing_doc_fails(tmp_path):
    result = reference_check.validate_reference_doc(tmp_path / "missing.md")
    assert result.status == "FAIL"
    assert "Reference survey document is missing." in result.errors


def test_complete_doc_passes(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text())

    result = reference_check.validate_reference_doc(path)
    assert result.status == "PASS"
    assert result.errors == ()


def test_missing_project_fails(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text().replace("Hummingbot", ""))

    result = reference_check.validate_reference_doc(path)
    assert result.status == "FAIL"
    assert "Hummingbot" in result.missing_projects


def test_missing_pattern_fails(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text().replace("Immutable fill ledger", ""))

    result = reference_check.validate_reference_doc(path)
    assert result.status == "FAIL"
    assert "Immutable fill ledger" in result.missing_patterns


def test_missing_safety_phrase_fails(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text().replace("Do not copy GPL code.", ""))

    result = reference_check.validate_reference_doc(path)
    assert result.status == "FAIL"
    assert "Do not copy GPL code" in result.missing_safety_phrases


def test_missing_next_patch_fails(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text().replace("P2-011", ""))

    result = reference_check.validate_reference_doc(path)
    assert result.status == "FAIL"
    assert "P2-011" in result.missing_next_patches


def test_render_pass_contains_verdict(tmp_path):
    path = tmp_path / "docs" / "OPEN_SOURCE_BOT_PLUMBING_SURVEY.md"
    write_doc(path, complete_doc_text())

    result = reference_check.validate_reference_doc(path)
    rendered = reference_check.render(result)

    assert "Status: PASS" in rendered
    assert "Reference survey satisfies" in rendered


def test_strict_fail_returns_one(tmp_path):
    code = reference_check.main(["--path", str(tmp_path / "missing.md"), "--strict"])
    assert code == 1


def test_forbidden_imports_absent():
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "import requests",
        "from requests",
        "import urllib",
        "import subprocess",
        "os.environ",
        "load_dotenv",
        "import coinbase",
        "from coinbase",
        "import alpaca",
        "from alpaca",
    ]
    for token in forbidden:
        assert token not in text
