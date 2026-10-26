from ofspectrum import OfSpectrum, StreamEncodePool


def test_exported_pool_constructor_keeps_preexisting_call_signature_valid():
    client = OfSpectrum(api_key="fixture-key")
    pool = StreamEncodePool(
        client.audio, token_id="fixture-token", connections=1, sample_rate=48000,
        channels=1, strength=1.0, smooth=True, verify_and_reencode=False,
        timeout=None,
    )
    try:
        assert pool._interval_seconds is None
    finally:
        pool.close()
        client.close()
