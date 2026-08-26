# Developer Build Specification: Local Speech-to-Text Desktop App

**Document status:** Living specification — v1.0
**Audience:** Any developer continuing work on this codebase. Read this fully before writing code.
**Rule:** If implementation and this document disagree, fix the discrepancy in BOTH places and note it in the PR description.

---

## 1. Product Goal

A desktop transcription app that runs **fully on the user's machine**:

- Open-source models only, no cloud API calls for inference.
- High-accuracy transcription (target WER < 8% on clean audio).
- Speaker diarization, word-level timestamps, translation mode, custom vocabulary.
- Zero recurring cost. No audio ever leaves the device.

**Platforms:** Windows 10/11 x64 (primary), macOS 13+ Apple Silicon & Intel (secondary).
**Packaging:** Signed installers (NSIS on Windows, DMG on macOS).

---

## 2. Tech Stack (do not substitute without discussion)

| Layer | Choice | Rationale |
|---|---|---|
| Shell / runtime | **Tauri 2.x** | Small binaries, native perf, sidecar process support |
| Frontend | **SvelteKit + TypeScript** | Fast, small bundle |
| Backend service | **Python 3.11 sidecar** | faster-whisper/pyannote ecosystem is Python-native |
| IPC | **Local HTTP over loopback** (`127.0.0.1`, random port) + SSE for progress events | Simpler to debug than gRPC; upgrade path documented in §8 |
| ASR engine | **faster-whisper** (CTranslate2) | Speed + quantization support |
| Optional GPU engine | **NeMo Parakeet/Canary** backend behind an interface flag | Best WER/speed on NVIDIA GPUs |
| VAD | **Silero VAD v5** (ONNX) | Robust, tiny, kills silence hallucination |
| Alignment | **WhisperX alignment** (wav2vec2 forced aligner) | Word-level timestamps |
| Diarization | **pyannote.audio 3.1** | Acceptable accuracy for 2–5 speakers |
| Denoise | **RNNoise** native lib via Python bindings | Light denoise only, user-togglable |
| Audio I/O | `soundfile` + `librosa` (batch), `sounddevice` (live mic) | Established libs |

### Model defaults

| Condition | Model |
|---|---|
| NVIDIA GPU ≥ 6 GB VRAM | `large-v3` float16 (+ optional Parakeet toggle) |
| NVIDIA GPU < 6 GB VRAM | `large-v3` int8_float16 or `medium` float16 |
| CPU only | `medium` int8 (default); user may select small/base |
| Live streaming mode | `distil-whisper/small.en` or `base` chunked every 3–5 s |

Model files live in app data:
- Windows: `%LOCALAPPDATA%\<AppName>\models`
- macOS: `~/Library/Application Support/<AppName>/models`

First-run downloads models with SHA-256 checksum verification against `docs/MODEL_MANIFEST.json`. Never auto-download without visible progress and a cancel button.


---

## 3. Repository Layout

```
/
├── src/                      # SvelteKit frontend
│   ├── lib/components/       # FileLoader, MicController, SettingsPanel,
│   │                         # TranscriptEditor, ExportDialog, ProgressBar
│   ├── lib/stores/           # appState.svelte.ts, settings.svelte.ts
│   ├── lib/types/            # TS mirrors of IPC schemas (§5)
│   └── routes/
├── src-tauri/                # Tauri shell: window mgmt, sidecar spawn, fs dialogs
├── backend/
│   ├── main.py               # Loopback HTTP/SSE server entrypoint
│   ├── core/
│   │   ├── audio_preprocess.py   # RMS normalize, trim, denoise
│   │   ├── vad_segmenter.py      # Silero VAD -> speech chunks
│   │   ├── transcriber.py        # Engine-agnostic ASR interface
│   │   ├── engines/
│   │   │   ├── faster_whisper_engine.py
│   │   │   └── parakeet_engine.py     # optional import, feature-flagged
│   │   ├── aligner.py            # WhisperX word-level alignment
│   │   ├── diarizer.py           # pyannote wrapper + speaker naming
│   │   ├── postprocess.py        # punctuation/casing restore, custom vocab
│   │   └── exporter.py           # TXT, SRT, VTT, JSON writers
│   ├── ipc/
│   │   ├── schemas.py            # Pydantic models mirroring §5 contracts
│   │   └── events.py             # SSE emitter (progress/log/done/error)
│   └── tests/
├── scripts/run_benchmarks.py
├── docs/
│   ├── DEVELOPMENT_SPEC.md       # ← you are here
│   ├── HANDOFF_CHECKLIST.md      # task board for new coders
│   ├── BENCHMARKS.md             # results table (see §10)
│   └── MODEL_MANIFEST.json       # urls + sha256 of downloadable models
```

**Coding conventions**
- Python: `ruff` lint+format, type hints mandatory (`mypy --strict` on new modules), pytest colocated in `backend/tests/`.
- TS/Svelte: ESLint + Prettier, no `any`, typed stores.
- Every pipeline stage exposes a pure function (typed input → typed output) where possible; streaming/live code is the documented exception.

---

## 4. Pipeline Data Flow

Batch mode (file import):

```
AudioFile
  → [audio_preprocess]  PCM16 mono 16 kHz float32, RMS-normalized to -20 dBFS,
                        head/tail silence trimmed (threshold -45 dBFS),
                        optional RNNoise pass (user toggle)
  → [vad_segmenter]     speech segments [{start_s, end_s}] (Silero, threshold 0.5,
                        min_speech 0.25 s, pad 0.2 s); non-speech regions marked
                        explicitly and NEVER sent to ASR (anti-hallucination rule)
  → [transcriber]       per-chunk text + timestamps + detected language;
                        custom vocabulary injected as initial_prompt tokens
                        (faster-whisper) or hotwords where supported
  → [aligner]           word-level timings merged into segment tree
  → [diarizer]          pyannote embeddings → speaker turns → mapped onto words
                        via max temporal overlap; labels "Speaker 1..N"
  → [postprocess]       punctuation/casing restoration, vocab term cleanup,
                        hallucination filter (see §7)
  → [exporter]          TranscriptDocument → TXT / SRT / VTT / JSON
```

Streaming mode (live mic):
- Capture 16 kHz mono blocks → rolling ring buffer with backpressure policy.
- VAD gates emission; transcribe trailing chunks every ~4 s using the small draft model.
- On stop, a final pass re-transcribes full audio with the large model ("live draft, final polish").
- Streaming output is flagged `draft: true` in transcript JSON until the final pass completes.

Translation mode uses Whisper `task=translate` (X→English); original-language transcript retained alongside.

---

## 5. IPC Contracts (single source of truth)

Frontend ↔ backend exchange JSON matching these Pydantic schemas; mirror them in TS types under `src/lib/types/`. **Change schemas.py and TS types together in the same commit** — no ad-hoc fields.

```python
class TranscriptWord(BaseModel):
    start: float
    end: float
    text: str
    confidence: float
    speaker: str | None = None  # "Speaker 1"
    low_confidence: bool = False


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    words: list[TranscriptWord]
    language: str | None = None
    draft: bool = False


class TranscriptDocument(BaseModel):
    schema_version: Literal[1]
    source_file: str | None
    duration_s: float
    language: str  # ISO 639-1
    segments: list[TranscriptSegment]
    vocabulary_applied: list[str]


class JobStatus(BaseModel):
    job_id: str
    stage: Literal[
        "queued",
        "preprocess",
        "vad",
        "transcribe",
        "align",
        "diarize",
        "postprocess",
        "export",
        "done",
        "error",
        "cancelled",
    ]
    progress: float  # 0.0–1.0 within current stage
    overall_progress: float  # weighted across stages
    message: str | None
```

Endpoints (loopback HTTP):

```
POST /jobs/batch          {file_path, settings}         → {job_id}
POST /jobs/stream/start   {settings}                    → {job_id}
POST /jobs/stream/chunk   {job_id}   (binary PCM body)  → 202
POST /jobs/stream/stop    {job_id}                      → 200
POST /jobs/cancel         {job_id}                      → 200
GET  /events              SSE stream of JobStatus events
GET  /transcript/{job_id}                               → TranscriptDocument
GET  /health              engine availability, model inventory, device info
```

Settings object (persisted client-side, sent with each job):
`model_size`, `device(auto|cuda|cpu)`, `compute_type(int8|int8_float16|float16)`,
`denoise(bool)`, `diarize(bool)`, `min/max_speakers(2–5, optional)`,
`translate_to_english(bool)`, `custom_vocabulary(list[str])`,
`vad_threshold(0.0–1.0)`, `export_formats(list[str])`.

---

## 6. GPU / Device Strategy

1. On startup probe devices: CUDA availability (via ctranslate2), VRAM size, CPU core count.
2. `/health` returns the capability map; the Settings panel reflects it and explains choices to users.
3. Fallback ladder: if requested model+device fails to load → log warning → step down (`large-v3 fp16` → `large-v3 int8_float16` → `medium int8`) rather than hard-fail.
4. Only one model instance resident at a time. LRU-unload the streaming draft model before loading a batch model. Never create more than one CUDA context.
5. Batch long files process chunks sequentially with a bounded queue; default RAM cap ~70% of available memory.

---

## 7. Hallucination & Quality Guards (mandatory)

These exist because Whisper repeats/hallucinates on silence or music. Do not remove:

1. Non-speech VAD regions never reach ASR (§4).
2. Repetition collapse detector: if chunk text contains ≥4 identical consecutive token n-grams → re-run that chunk with `no_repeat_ngram_size=6, temperature=0.4`.
3. Segments shorter than VAD min_speech are dropped entirely.
4. Confidence floor: aligned words below 0.35 flagged `low_confidence` and highlighted in UI.
5. Custom-vocab post-pass applies longest-match replacement preserving case variants.

---

## 8. Upgrade Paths (documented decisions)

- **gRPC:** deliberately deferred. If loopback HTTP/SSE overhead becomes measurable (>10 ms round-trip), introduce `ipc/transport.py` abstraction; callers must not hand-build URLs.
- **Multi-GPU:** out of scope v1; keep transcriber stateless with respect to device selection so a device registry can slot in later.
- **Parakeet engine:** stretch goal, feature-flagged off until after M1; keep the interface stub compiling.

---

## 9. Milestones (in order; each ends with a runnable build)

| # | Milestone | Deliverable | Done when |
|---|---|---|---|
| M0 | Repo scaffold | Tauri+SvelteKit shell, Python sidecar spawns, `/health` reachable from UI | App opens, health panel shows device info |
| M1 | Batch transcription MVP | preprocess→vad→transcribe→TXT/SRT export with progress UI end-to-end | 30-min MP3 → accurate TXT with working progress bar + cancellation |
| M2 | Word alignment | aligner wired, words render on segment click, VTT export | Word timestamps verified ±50 ms on fixture set |
| M3 | Diarization | pyannote integrated w/ HF license gate, editable speaker labels in UI | 3-speaker meeting sample reads correctly |
| M4 | Custom vocabulary + translation | settings UI ↔ transcriber wiring complete | Hotword appears verbatim in test fixture transcript |
| M5 | Live mic mode | streaming controller, draft/final two-pass | 5-min live session stays synchronized, memory stable |
| M6 | Perf & packaging | installers, cold-start <5 s, benchmark suite scripted | Benchmarks recorded in docs/BENCHMARKS.md |

**Milestone discipline:** a milestone is not done until `pytest backend/tests -q` and `npm run build && cargo tauri build` pass and HANDOFF_CHECKLIST.md is updated.

---

## 10. Benchmarks & Acceptance Criteria

Fixtures under `backend/tests/fixtures/` (≤60 s clips committed; the 1-hour media referenced by manifest + download script, not committed):

1. Clean podcast (single speaker, studio mic)
2. Phone-call quality audio (8 kHz artifacts)
3. Multi-speaker meeting (3 speakers, mild overlap)
4. Silence-only (hallucination probe)

Protocol: run `scripts/run_benchmarks.py` → WER (jiwer) vs reference transcripts, RTF, peak RSS/VRAM. Append results to docs/BENCHMARKS.md with date + commit hash.

Acceptance criteria (v1 sign-off):
- [ ] Clean-audio WER < 8% with large-v3 or Parakeet
- [ ] Zero hallucination output during pure-silence fixture
- [ ] Diarization usable for 2–5 speakers (DER spot-check ≤15% on meeting fixture; otherwise document limitation)
- [ ] Fully offline confirmed (firewall-blocked / network-monitor audit)
- [ ] Cold start < 5 s to interactive UI
- [ ] 1-hour WAV/MP3 batch completes without OOM or unbounded memory growth; cancellation responsive <1 s
- [ ] Windows NSIS + macOS DMG installers produced by CI

---

## 11. Licensing & Privacy Notes (legal hygiene)

- faster-whisper: MIT. WhisperX, Silero VAD, RNNoise: permissive licenses — verify headers before vendoring.
- pyannote models are MIT **but** require accepting terms on Hugging Face. Implement a clean in-app gate: user supplies their own HF token once, we cache locally, token never leaves the machine. Graceful mode if unavailable: skip diarization with clear messaging.
- No telemetry by default. Opt-in crash reports transmit redacted stack traces only — never transcripts or audio — and only after explicit consent.

---

## 12. New-Developer Quickstart

```powershell
# Prereqs: Node 20+, Rust toolchain, Python 3.11, ffmpeg on PATH, GitHub access per docs/GITHUB_WORKFLOW.md
git clone https://github.com/FreeDeathTV/scalper.git && cd scalper
git checkout -b feat/<issue#>-<slug>            # never commit to main directly
npm install
python -m venv backend/.venv
backend\.venv\Scripts\activate && pip install -r backend/requirements.txt
python scripts/download_models.py --tier default   # verifies MODEL_MANIFEST.json checksums
npm run tauri dev                                   # frontend + sidecar together
pytest backend/tests -q                             # sanity check
```

Read order: this spec §1–§7 → HANDOFF_CHECKLIST.md → claim an unchecked item → open PR referencing that checklist entry.

---

## 13. GitHub Process (summary — full rules in docs/GITHUB_WORKFLOW.md)

- Trunk-based: short-lived branches off protected `main`; no direct pushes; CI green + 1 review (2 for IPC schema changes) required to merge.
- Conventional Commits; small PRs ≤ ~400 lines, one logical change each.
- Milestones M0–M6 tagged as `m0`–`m6` when their acceptance line passes; tags are the rollback checkpoints.
- **Revert-first policy:** misbehavior on `main` → immediate revert PR, investigate after. Full playbook in GITHUB_WORKFLOW.md §4.
- Risky features land behind settings flags so disabling them is a one-line revert.