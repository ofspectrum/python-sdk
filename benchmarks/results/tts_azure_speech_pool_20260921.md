# Azure AI Speech TTS latency — 2026-09-21

Region: `eastus`. Voice: `en-US-AvaNeural`. Output: MP3. Three runs per target tier.
Each run synthesized one clip and encoded those exact bytes through both the file endpoint and a prewarmed persistent pool. The first pool warmup was 238 ms and was excluded from encode timings.

| Target | Actual audio | Native TTS | File encode | Pool encode | Native + file | Native + pool | Pool savings |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 s | 5.23 s | 560 ms | 1907 ms | 1256 ms | 2467 ms | 1817 ms | +650 ms |
| 10 s | 10.37 s | 434 ms | 1929 ms | 1175 ms | 2363 ms | 1609 ms | +754 ms |
| 30 s | 30.65 s | 537 ms | 2703 ms | 2918 ms | 3240 ms | 3455 ms | -215 ms |

The wrapped `AzureSpeechTTS` call returned playable MP3 with the default pool. Decoding that output found the watermark and the configured token. A separate live synchronous call followed by `speak_text_async(...).get()` on the same wrapper reused one pool object.

These are three runs per tier with repeated text, so provider-side caching or service variation can affect the observed TTS time. Negative pool savings means the pool was slower for that tier.

Full per-run data: [JSON](tts_azure_speech_pool_20260921.json).
