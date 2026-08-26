/**
 * Loopback HTTP/SSE client for the Python sidecar (spec §5).
 * The sidecar port is provided by the Tauri shell; in browser dev mode we
 * default to SCALPER_PORT env or 8000 for manual uvicorn runs.
 */

import type { HealthReport, JobStatus, Settings, TranscriptDocument } from '$lib/types/ipc';

const PORT = import.meta.env.VITE_SCALPER_PORT ?? '8000';
const BASE = `http://127.0.0.1:${PORT}`;

async function post<T>(path: string, body?: unknown): Promise<T> {
	const res = await fetch(`${BASE}${path}`, {
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
	const res = await fetch(`${BASE}/health`);
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
export function onJobEvent(handler: (status: JobStatus) => void): () => void {
	const es = new EventSource(`${BASE}/events`);
	es.onmessage = (ev) => handler(JSON.parse(ev.data) as JobStatus);
	return () => es.close();
}

export async function getTranscript(jobId: string): Promise<TranscriptDocument> {
	const res = await fetch(`${BASE}/transcript/${jobId}`);
	if (!res.ok) throw new Error(await describeError(res));
	return res.json();
}
