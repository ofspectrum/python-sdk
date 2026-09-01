# ElevenLabs services duration latency benchmark

- Run completed: 2026-08-31
- Duration targets: 2s, 5s, 10s, 30s
- Consecutive runs per target: 3
- Measurement order: call the native ElevenLabs service once, then encode the exact returned audio bytes
- `encode on` = native service latency + OfSpectrum encode latency
- Detailed per-run data: `elevenlabs_services_duration_latency_20260831T192903Z.json`

All values below are three-run averages in milliseconds. `Added` is the OfSpectrum encode latency. Percentages compare the average added latency with the average native-service latency. Actual output duration can differ from the target for generative services.

| Service | Target | Actual output | Encode off | Encode on | Added | Increase | Successful pairs |
|---|---:|---:|---:|---:|---:|---:|---:|
| Speech-to-Speech | 2s | 2.043s | 1,130.24 | — | — | — | 0/3 |
| Speech-to-Speech | 5s | 5.016s | 1,225.76 | 3,087.14 | 1,861.37 | 151.9% | 3/3 |
| Speech-to-Speech | 10s | 10.031s | 1,593.20 | 3,597.42 | 2,004.22 | 125.8% | 3/3 |
| Speech-to-Speech | 30s | 30.000s | 4,536.01 | 7,367.41 | 2,831.41 | 62.4% | 3/3 |
| Sound Effects | 2s | 2.000s | 1,941.31 | — | — | — | 0/3 |
| Sound Effects | 5s | 5.000s | 2,978.45 | 4,890.73 | 1,912.27 | 64.2% | 3/3 |
| Sound Effects | 10s | 10.000s | 3,006.24 | 5,058.11 | 2,051.87 | 68.3% | 3/3 |
| Sound Effects | 30s | 30.000s | 4,211.43 | 7,272.84 | 3,061.41 | 72.7% | 3/3 |
| Text-to-Dialogue | 2s | 2.800s | 1,203.49 | — | — | — | 0/3 |
| Text-to-Dialogue | 5s | 5.253s | 2,068.10 | 3,865.62 | 1,797.51 | 86.9% | 3/3 |
| Text-to-Dialogue | 10s | 10.560s | 3,499.49 | 5,510.89 | 2,011.40 | 57.5% | 3/3 |
| Text-to-Dialogue | 30s | 37.680s | 12,732.71 | 16,040.76 | 3,308.04 | 26.0% | 3/3 |
| Audio Isolation | 2s | — | — | — | — | — | 0/3 |
| Audio Isolation | 5s | 4.992s | 809.66 | 2,945.84 | 2,121.19 | 262.0% | 2/3 |
| Audio Isolation | 10s | 9.985s | 1,009.31 | 3,725.49 | 2,716.17 | 269.1% | 3/3 |
| Audio Isolation | 30s | 29.977s | 1,753.37 | 6,840.55 | 5,087.18 | 290.1% | 3/3 |
| Music Compose | 2s | — | — | — | — | — | 0/3 |
| Music Compose | 5s | 5.739s | 4,401.50 | 6,239.49 | 1,837.98 | 41.8% | 3/3 |
| Music Compose | 10s | 10.048s | 5,649.42 | 7,834.06 | 2,184.64 | 38.7% | 3/3 |
| Music Compose | 30s | 29.989s | 7,445.84 | 10,685.76 | 3,239.92 | 43.5% | 3/3 |
| Video-to-Music | 2s | 3.056s | 8,962.00 | — | — | — | 0/3 |
| Video-to-Music | 5s | 6.740s | 10,685.25 | 12,799.70 | 2,114.45 | 19.8% | 3/3 |
| Video-to-Music | 10s | 10.057s | 14,483.46 | 16,695.72 | 2,212.26 | 15.3% | 3/3 |
| Video-to-Music | 30s | 36.049s | 13,877.64 | 17,504.15 | 3,626.51 | 26.1% | 3/3 |

## Failures and service constraints

- Speech-to-Speech, Sound Effects, Text-to-Dialogue, and Video-to-Music: all three short-tier encode attempts returned `PROC_4002`, indicating that the resulting audio was too short for this watermark token.
- Audio Isolation 2s: ElevenLabs rejected all three native requests because this endpoint requires at least 4.6 seconds of input audio, so encode was not attempted.
- Music Compose 2s: ElevenLabs rejected all three native requests because `music_length_ms` must be at least 3,000 ms, so encode was not attempted.
- Audio Isolation 5s: two pairs succeeded; one encode attempt returned `PROC_4002: Audio input is not supported by Audio Encode V2`. Its summary is based on the two successful encode pairs, while the native average includes all three native calls.
- No automatic retries were used, so the report preserves service behavior from the original consecutive attempts.

## Interpretation

- For successful 5s and 10s generated MP3 results, watermark encoding generally added about 1.8–2.7 seconds.
- For successful 30s MP3 results, it generally added about 2.8–3.6 seconds.
- Audio Isolation returned WAV data and showed a higher encode cost: about 2.1 seconds at 5s, 2.7 seconds at 10s, and 5.1 seconds at 30s.
- Relative percentage depends heavily on how fast the native endpoint is. Audio Isolation has low native latency, so encode dominates the percentage; Video-to-Music has high native latency, so the same few seconds appear as a smaller percentage.
