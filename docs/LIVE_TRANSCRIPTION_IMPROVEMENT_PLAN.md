# Live Transcription Improvement Tick Sheet

This is the working plan for improving system-audio live transcription. Read
`docs/GITHUB_WORKFLOW.md` before starting work. Each item should be completed
in a focused commit or pull request, with tests and evidence recorded in the PR.

## Current baseline

- [x] Edge/WebView2 system-audio capture works through `getDisplayMedia`.
- [x] Live PCM is sent to the sidecar over `/ws/live`.
- [x] Live segments are delivered through the shared `/events` SSE stream.
- [x] Session IDs prevent stale live sessions contaminating a new transcript.
- [x] Broken CUDA runtime falls back to CPU.
- [x] Base CPU model warms during backend startup and is reused.
- [x] Live hard chunk limit reduced from 12 seconds to 6 seconds.
- [ ] Live draft/final transcript behavior matches the development specification.
- [ ] Live latency and memory behavior are measured with repeatable benchmarks.
- [x] Optional language lock is available to stabilize recognition when auto-detection is unreliable.
- [x] Transcript can be copied to the clipboard and cleared without resetting the app.

## Priority 1 — latency and responsiveness

### 1. Add live timing instrumentation

- [ ] Record capture, utterance-close, queue, transcription-complete, and UI-render timestamps.
- [ ] Expose queue depth, model/device, captured seconds, and real-time factor in diagnostics.
- [ ] Add a benchmark command or fixture for a repeatable 60-second speech sample.
- [ ] Acceptance: report p50/p95 result latency and real-time factor for Base, Small,
  and Medium on CPU and supported CUDA.

### 2. Implement rolling live chunks

- [ ] Replace the single hard-limit buffer with configurable 3–5 second rolling chunks.
- [x] Add 0.3–0.6 second overlap between adjacent chunks (0.5 seconds).
- [ ] Add stable chunk/segment IDs.
- [x] Deduplicate repeated words at overlap boundaries.
- [ ] Provide Fast, Balanced, and Quality latency presets.
- [ ] Acceptance: Fast mode produces visible text within 3–5 seconds during continuous speech
  without duplicated boundary text.

### 3. Make Stop and Cancel distinct

- [x] Stop accepting audio immediately when the user presses Stop.
- [x] Add “Stop and finalize” behavior separately from immediate cancellation.
- [x] Cancel queued chunks without waiting for unrelated work.
- [x] Emit `cancelled` for immediate cancellation and `done` only after finalization.
- [ ] Add a regression test proving immediate cancellation completes within one second.

## Priority 2 — accuracy and transcript behavior

### 3. Transcript usability

- [x] Add Copy transcript control for live and batch text.
- [x] Add Clear transcript control without resetting capture/settings state.

### 4. Add draft and final transcript passes

- [ ] Emit live chunks as `draft: true`.
- [ ] Keep captured audio for the session.
- [ ] On Stop and finalize, transcribe with the selected quality model.
- [ ] Replace drafts with final segments while preserving timestamps.
- [ ] Add a regression test for draft replacement and overlap deduplication.
- [ ] Acceptance: the transcript is fast during capture and receives a clean final pass on Stop.

### 5. Improve language and audio controls

- [x] Add an optional language selector, including an English lock.
- [ ] Show capture level and silence/audio-track diagnostics.
- [ ] Detect and report near-silent or missing audio before starting ASR.
- [ ] Add optional normalization and denoise for browser-captured audio.
- [ ] Compare WER for automatic language detection versus a forced language.

## Priority 3 — device and model reliability

### 6. Validate CUDA runtime usability

- [ ] Distinguish CUDA device detection from CUDA runtime usability.
- [ ] Verify required libraries such as `cublas64_12.dll` before selecting CUDA.
- [ ] Report “CUDA runtime incomplete — using CPU” in health and the UI.
- [ ] Add tests for usable CUDA, missing runtime libraries, and CPU fallback.

### 7. Harden model lifecycle and warmup

- [x] Reuse warmed models across live sessions.
- [ ] Prevent duplicate model loads across simultaneous sessions.
- [ ] Add visible warmup/download progress and a cancel path.
- [ ] Unload models when memory pressure requires it.
- [ ] Store managed model files in the documented application model directory.
- [ ] Add cold-start and warm-start timing measurements.

## Priority 4 — verification and release

### 8. Add integration and soak coverage

- [ ] Add a real Edge capture integration test or documented manual test evidence.
- [ ] Run a 30-minute live session and record RSS, queue depth, and dropped audio.
- [ ] Test repeated start/stop cycles without refreshing the window.
- [ ] Test multiple browser tabs and stale SSE/WebSocket connections.
- [ ] Verify offline operation after models are cached.

### 9. Complete packaging readiness

- [ ] Verify the full Tauri app, not only the Vite browser development server.
- [ ] Build and test the Windows installer.
- [ ] Confirm sidecar startup, model discovery, and graceful shutdown in the packaged app.
- [ ] Update `docs/BENCHMARKS.md` with latency, WER, memory, and startup results.

## Working rules

- Keep one logical change per PR and update this checklist in the same PR.
- Do not commit model weights, credentials, long audio, or generated build artifacts.
- For IPC/schema changes, update both `backend/ipc/schemas.py` and
  `src/lib/types/ipc.ts`.
- Required validation for code changes:

```powershell
cd backend
python -m pytest tests -q
cd ..
npm run check
npm run lint
```
