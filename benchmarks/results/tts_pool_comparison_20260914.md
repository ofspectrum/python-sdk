# Prewarmed stream-pool latency comparison — 2026-09-14

Three runs per 5/10/30-second target tier, with no audio warmup request. A single persistent stream connection was opened and prewarmed using `heartbeat()` before timing. Each run generated one native TTS result and sent the exact same source audio to both the normal file encoder and the prewarmed pool. Encode order alternated between runs. Connection warmup is excluded from encode latency.

| Provider / model | Pool warmup | Target | Actual audio | Native TTS | File encode | Pooled encode | Encode savings | File total | Pooled total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemini 3.1 Flash TTS | 436 ms | 5 s | 5.95 s | 5,799 ms | 2,901 ms | 1,123 ms | 1,778 ms (61%) | 8,700 ms | 6,922 ms |
| Gemini 3.1 Flash TTS | 436 ms | 10 s | 10.52 s | 8,810 ms | 3,927 ms | 1,173 ms | 2,754 ms (70%) | 12,737 ms | 9,983 ms |
| Gemini 3.1 Flash TTS | 436 ms | 30 s | 30.27 s | 21,405 ms | 6,941 ms | 2,552 ms | 4,389 ms (63%) | 28,345 ms | 23,957 ms |
| OpenAI gpt-4o-mini-tts | 391 ms | 5 s | 5.90 s | 2,152 ms | 2,064 ms | 1,235 ms | 828 ms (40%) | 4,216 ms | 3,387 ms |
| OpenAI gpt-4o-mini-tts | 391 ms | 10 s | 10.11 s | 2,524 ms | 2,101 ms | 1,388 ms | 713 ms (34%) | 4,625 ms | 3,912 ms |
| OpenAI gpt-4o-mini-tts | 391 ms | 30 s | 31.06 s | 4,615 ms | 3,743 ms | 2,990 ms | 753 ms (20%) | 8,358 ms | 7,605 ms |

The persistent pool reduced average encode latency at every measured tier. The relative gain was larger for Gemini in this run. Pool warmup cost less than 0.5 seconds for both providers and is paid once per persistent connection rather than once per audio request.

These are three-sample measurements from one session. The JSON files contain every run and the average, p50, and p95 summaries. More iterations are required for a stable tail-latency estimate.

- Gemini data: `tts_gemini_pool_comparison_20260914.json`
- OpenAI data: `tts_openai_pool_comparison_20260914.json`
