from pathlib import Path

import ofspectrum
from ofspectrum import __version__


def test_package_versions_are_1_2_0():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    assert __version__ == "1.2.0"
    assert 'version = "1.2.0"' in pyproject


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
