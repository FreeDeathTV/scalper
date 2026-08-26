# Scalper Transcriber

Fully-local speech-to-text desktop app. No cloud inference, no per-minute costs, no audio leaving the machine.

**Start here as a contributor:** [`docs/DEVELOPMENT_SPEC.md`](docs/DEVELOPMENT_SPEC.md) → [`docs/GITHUB_WORKFLOW.md`](docs/GITHUB_WORKFLOW.md) → [`docs/HANDOFF_CHECKLIST.md`](docs/HANDOFF_CHECKLIST.md).

## Quick start (dev)

```powershell
# Prereqs: Node 20+, Rust toolchain, Python 3.11+, ffmpeg on PATH
npm install
python -m venv backend/.venv
backend\.venv\Scripts\activate && pip install -r backend/requirements.txt
python scripts/download_models.py --tier default
npm run tauri dev        # window + sidecar together

# Backend-only iteration (no UI):
cd backend && uvicorn main:app --host 127.0.0.1 --port 8000

# Tests (must stay green on every commit — GITHUB_WORKFLOW §1):
cd backend && python -m pytest tests -q
```

## Current status

| Milestone | State |
|---|---|
| M0 scaffold | **done**: Tauri shell + SvelteKit UI + FastAPI sidecar + IPC schemas + CI |
| M1 batch MVP | pipeline orchestrator wired; whisper engine behind guarded import; needs model install + E2E |
| M2–M6 | interfaces stubbed per spec; see HANDOFF_CHECKLIST |

## Layout

- `src/` — SvelteKit frontend; `src/lib/types/ipc.ts` mirrors backend schemas (change both together)
- `src-tauri/` — Rust shell, spawns `backend` sidecar on a random loopback port
- `backend/` — FastAPI + pipeline stages (`core/audio_preprocess` … `exporter`)
- `docs/` — spec, workflow, checklist, benchmarks, MODEL_MANIFEST.json
