# TTS latency comparison — 2026-09-14

Three paired runs per target tier; no warmups. Each run times native TTS, then sends that exact audio to OfSpectrum for encoding. Combined latency is the sum of those two measurements. Targets are approximate; actual durations are reported below.

| Provider / model | Target | Actual audio avg | Native TTS avg | Encode avg | Combined avg | Encode / native |
|---|---:|---:|---:|---:|---:|---:|
| Gemini 3.1 Flash TTS | 5 s | 5.88 s | 5,506 ms | 2,809 ms | 8,315 ms | 51% |
| Gemini 3.1 Flash TTS | 10 s | 10.23 s | 7,859 ms | 3,463 ms | 11,322 ms | 44% |
| Gemini 3.1 Flash TTS | 30 s | 30.61 s | 20,091 ms | 6,647 ms | 26,738 ms | 33% |
| OpenAI gpt-4o-mini-tts | 5 s | 5.51 s | 2,077 ms | 2,044 ms | 4,121 ms | 98% |
| OpenAI gpt-4o-mini-tts | 10 s | 10.39 s | 2,521 ms | 2,136 ms | 4,657 ms | 85% |
| OpenAI gpt-4o-mini-tts | 30 s | 31.06 s | 5,320 ms | 3,216 ms | 8,536 ms | 60% |

The individual JSON reports contain every run plus average, p50, and p95 statistics. Three samples are useful for a first latency check but are not enough for a stable tail-latency estimate.

The first Gemini attempt encountered an OfSpectrum `PROC_4004` service-unavailable error during encoding. A one-run retry and the subsequent three-run set completed; the failed attempt is excluded from the table.

- Gemini data: `tts_gemini_3_1_flash_20260914.json`
- OpenAI data: `tts_openai_gpt_4o_mini_tts_20260914.json`
