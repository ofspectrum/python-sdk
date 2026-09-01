import pytest

from benchmarks.elevenlabs_latency import output_filename, percentile, summary


def test_percentile_uses_linear_interpolation():
    assert percentile([1.0, 2.0, 3.0], 0.50) == 2.0
    assert percentile([1.0, 2.0, 3.0], 0.95) == pytest.approx(2.9)


def test_summary_reports_average_p50_and_p95_in_milliseconds():
    result = summary([0.1, 0.2, 0.3])

    assert result == {
        "average_ms": pytest.approx(200.0),
        "p50_ms": pytest.approx(200.0),
        "p95_ms": pytest.approx(290.0),
    }


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("mp3_44100_128", "elevenlabs-output.mp3"),
        ("wav_44100", "elevenlabs-output.wav"),
        ("auto", "elevenlabs-output.mp3"),
    ],
)
def test_output_filename(output_format, expected):
    assert output_filename(output_format) == expected
