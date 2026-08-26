# Handoff Checklist — Local Speech-to-Text App

For each coder picking up work: read docs/GITHUB_WORKFLOW.md first (branching, PR rules, revert playbook), then docs/DEVELOPMENT_SPEC.md §9 for milestone context. Claim items below, create a GitHub issue from them, and update this file's statuses in the same PR that changes code.

Issue templates: Task (work items) and Bug report (reversions get flagged here — see workflow doc §1 golden rule 4).

Status key: ☐ not started · ◐ partially done · ☑ done · ❌ blocked (note why)

## M0 — Scaffold
- ☑ Tauri 2 + SvelteKit shell builds and opens empty window (Win/macOS)
  *Verified: `cargo check` exit 0 (Win), `vite build` static bundle OK, placeholder icon generated. Full `npm run tauri build` installer pass still owed before tagging m0.*
- ◐ Python sidecar launches from Tauri, loopback port handshake, graceful shutdown
  *Code complete (`src-tauri/src/lib.rs`: venv detection, random port, health-wait emit `sidecar-ready`, RunEvent::Exit kill). Backend verified standalone via uvicorn smoke test; the Tauri-spawned path needs one manual `npm run tauri dev` confirmation.*
- ☑ `/health` endpoint reporting device capabilities (CUDA/VRAM/CPU cores)
  *Verified live: returns engines map + devices info; degrades to `status:"degraded"` when models absent.*
- ☑ Settings persistence layer (basic: localStorage via `appState.svelte.ts`; swap to Tauri fs plugin when it lands)


## M1 — Batch transcription MVP
- ☐ `audio_preprocess`: RMS normalize → trim → optional RNNoise, unit tests
- ☐ `vad_segmenter`: Silero integration, segment JSON out, non-speech exclusion enforced
- ☐ `transcriber.faster_whisper_engine`: device/compute-type fallback ladder implemented (spec §6)
- ☑ Model downloader script + SHA-256 verification against MODEL_MANIFEST.json
  *(silero-vad-v5 ONNX downloaded to ~/.scalper/models and pinned+verified; whisper CT2 weights fetch by pinned HF id on first run)*
- ☐ Progress: stage-weighted JobStatus over SSE consumed by ProgressBar component
- ☐ Exporters: TXT + SRT writers, matches format examples in tests/fixtures/exported/
- ☐ Cancellation path: POST /jobs/cancel stops mid-stage within 1 s (test required)

## M2 — Alignment
- ☐ `aligner`: WhisperX wav2vec2 alignment wired into pipeline
- ☐ Word-level rendering + clickable seek in TranscriptEditor
- ☐ VTT export with word-level cues
- ☐ Timestamp accuracy ±50 ms verification on fixture set (blocker: needs M1 transcriber + fixtures first)

## M3 — Diarization
- ☐ HF token gate dialog (user-supplied, cached locally — see spec §11)
- ☐ `diarizer`: pyannote pipeline, min/max speaker constraint passthrough
- ☐ Speaker-turn-to-word mapping (max temporal overlap) incl. edge cases: overlaps, very short turns
- ☐ Editable speaker labels persisted in TranscriptDocument

## M4 — Vocabulary & translation
- ☐ Initial-prompt hotword injection path in faster-whisper engine + regression test fixture
- ☐ Postprocess longest-match vocabulary replacement (case-preserving)
- ☐ Translation mode (task=translate) retaining original-language transcript alongside
- ☐ Punctuation/casing restoration stage + toggle

## M5 — Live mic
- ☐ sounddevice capture at 16 kHz mono; ring buffer + backpressure policy documented
- ☐ Draft stream every ~4 s (small model) flagged `draft:true`
- ☐ Final two-pass polish on stop (large model), diff-safe merge into UI
- ☐ Memory soak test: 30-min session, RSS flat (evidence in docs/BENCHMARKS.md)

## M6 — Packaging & benchmarks
- ☐ Windows NSIS installer, code signing config stubbed for CI secrets
- ☐ macOS DMG build (Apple Silicon + Intel universal)
- ☐ Cold-start timing instrumentation + budget enforcement (<5 s alert)
- ☐ scripts/run_benchmarks.py producing WER/RTF/memory table → docs/BENCHMARKS.md
- ☐ Fixtures: clean podcast, phone-call, multi-speaker meeting, silence-only, 1-hour manifest
- ☐ Network-isolation audit performed offline (acceptance criteria spec §10)

## Cross-cutting (any time)
- ◐ CI pipeline: ruff+mypy(strict), eslint+prettier, pytest, cargo build matrix
  *Full local parity verified on Windows before first push (all jobs green). Remaining: add prettier frontend formatting check + macOS CI run; enable required-status-checks in repo settings.*
- ☐ Error taxonomy: user-readable messages for missing model / out-of-memory / bad file
- ☐ Docs: BUILD.md fast-start variant of spec §12 (optional contribution)

## Known risks / decisions log
- Parakeet backend de-scoped to stretch goal until M1 lands (keep `parakeet_engine.py` interface stub compiling, feature-flagged off).
- gRPC deferred — see spec §8; don't circumvent the transport abstraction.
- pyannote licensing = blocking dependency for M3; if org policy disallows HF token flow, evaluate `NeMo sortformer` alternative and record decision here.
