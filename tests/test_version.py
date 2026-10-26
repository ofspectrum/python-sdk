from pathlib import Path

import ofspectrum
from ofspectrum import __version__


def test_package_versions_are_1_5_0():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert __version__ == "1.5.0"
    assert 'version = "1.5.0"' in pyproject


def test_installation_guides_match_the_package_release():
    root = Path(__file__).parents[1]
    install_command = f'pip install "ofspectrum=={__version__}"'

    for name in ("README.md", "AGENT_GUIDE.md"):
        assert install_command in (root / name).read_text(encoding="utf-8")
    assert (
        "https://github.com/ofspectrum/python-sdk/blob/main/CHANGELOG.md"
        in (root / "README.md").read_text(encoding="utf-8")
    )


def test_current_release_has_documented_compatibility_notes():
    changelog = (Path(__file__).parents[1] / "CHANGELOG.md").read_text(
        encoding="utf-8"
    )
    release_marker = f"\n## {__version__} - "
    assert release_marker in changelog
    release_notes = changelog.split(release_marker, 1)[1].split("\n## ", 1)[0]

    for boundary in (
        "tokens.update()",
        "keyword-only",
        "save_file=False",
        'response_format="stream"',
        "one hour",
    ):
        assert boundary in release_notes
    assert "Both response formats still return `EncodeResult`" in release_notes
    assert "callers that need an `EncodeResult`" not in release_notes


def test_1_2_0_public_models_and_exceptions_are_exported():
    expected_exports = {
        "ConflictError",
        "PaymentRequiredError",
        "NotebookDesiredMedia",
        "NotebookDesiredState",
        "NotebookSaveSession",
        "NotebookSaveSessionStatus",
        "NotebookSaveSessionCancellation",
        "NotebookStagedUpload",
        "NotebookCommitMedia",
        "NotebookCommitResponse",
    }

    assert expected_exports <= set(ofspectrum.__all__)
    assert all(hasattr(ofspectrum, name) for name in expected_exports)
