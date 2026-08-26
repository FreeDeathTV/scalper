/**
 * Loopback HTTP/SSE client for the Python sidecar (spec §5).
 * The sidecar port is provided by the Tauri shell; in browser dev mode we
 * default to VITE_SCALPER_PORT or 8000 for manual uvicorn runs.
 */

import { invoke } from '@tauri-apps/api/core';

import type { HealthReport, JobStatus, Settings, TranscriptDocument } from '$lib/types/ipc';

// Tauri is the source of truth for the sidecar port; fall back to the dev env
// value (set for manual `npm run dev` + uvicorn), else 8000 for pure-browser.
const PORT = import.meta.env.VITE_SCALPER_PORT ?? '8000';

async function resolvePort(): Promise<string> {
	if (!import.meta.env.VITE_SCALPER_PORT && typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window) {
		try {
			const p = await invoke<number | null>('sidecar_port');
			if (typeof p === 'number' && p > 0) return String(p);
		} catch {
			/* fall back to env/default if the bridge isn't ready */
		}
	}
	return import.meta.env.VITE_SCALPER_PORT ?? '8000';
}

let BASE = `http://127.0.0.1:${PORT}`;
let ready: Promise<string> | null = null;

/** Wait for the sidecar port to be known before the first request. */
export function readyBase(): Promise<string> {
	if (!ready)
		ready = resolvePort().then((p) => {
			BASE = `http://127.0.0.1:${p}`;
			return BASE;
		});
	return ready;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
	const res = await fetch(`${await readyBase()}${path}`, {
		method: 'POST',
		headers: { 'content-type': 'application/json' },
		body: JSON.stringify(body ?? {})
	});
	if (!res.ok) throw new Error(await describeError(res));
	return res.json();
}

async function describeError(res: Response): Promise<string> {
	try {
		const data = await res.json();
		return typeof data.detail === 'string' ? data.detail : JSON.stringify(data);
	} catch {
		return `${res.status} ${res.statusText}`;
	}
}

export async function getHealth(): Promise<HealthReport> {
	const res = await fetch(`${await readyBase()}/health`);
	if (!res.ok) throw new Error('sidecar unreachable');
	return res.json();
}

export async function startBatchJob(filePath: string, settings: Settings): Promise<string> {
	const { job_id } = await post<{ job_id: string }>('/jobs/batch', {
		file_path: filePath,
		settings
	});
	return job_id;
}

export async function cancelJob(jobId: string): Promise<void> {
	await post('/jobs/cancel', { job_id: jobId });
}

/** Subscribe to all JobStatus events; returns an unsubscriber. */
export async function onJobEvent(
	handler: (status: JobStatus) => void
): Promise<() => void> {
	const es = new EventSource(`${await readyBase()}/events`);
	es.onmessage = (ev) => handler(JSON.parse(ev.data) as JobStatus);
	return () => es.close();
}

export async function getTranscript(jobId: string): Promise<TranscriptDocument> {
	const res = await fetch(`${await readyBase()}/transcript/${jobId}`);
	if (!res.ok) throw new Error(await describeError(res));
	return res.json();
}

/** Upload a system-audio capture WAV; returns the batch job id to poll. */
export async function uploadCapture(wav: Blob, settings: Settings): Promise<string> {
	const form = new FormData();
	form.append('file', wav, 'capture.wav');
	form.append('settings_json', JSON.stringify(settings));
	const res = await fetch(`${await readyBase()}/capture/upload`, { method: 'POST', body: form });
	if (!res.ok) throw new Error(await describeError(res));
	const { job_id } = (await res.json()) as { job_id: string };
	return job_id;
}

/** Poll until the job's transcript document is ready (server 404s until then). */
export async function waitForTranscript(
	jobId: string,
	timeoutMs = 10 * 60_000
): Promise<TranscriptDocument> {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			return await getTranscript(jobId);
		} catch {
			await new Promise((r) => setTimeout(r, 1500));
		}
	}
	throw new Error('timed out waiting for transcript');
}
