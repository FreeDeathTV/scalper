/**
 * Client-side transcript saving.
 * NOTE: the backend exporter (backend/core/exporter.py) remains canonical for
 * file formats written next to the source audio; this module only serializes
 * what the UI already holds so the user gets a local copy without IPC work.
 */

import type { TranscriptDocument } from '$lib/types/ipc';

function ts(seconds: number, comma = false): string {
	const ms = Math.round((seconds % 1) * 1000);
	const total = Math.floor(seconds);
	const h = String(Math.floor(total / 3600)).padStart(2, '0');
	const m = String(Math.floor((total % 3600) / 60)).padStart(2, '0');
	const s = String(total % 60).padStart(2, '0');
	return `${h}:${m}:${s}${comma ? ',' : '.'}${String(ms).padStart(3, '0')}`;
}

export function serialize(doc: TranscriptDocument, fmt: 'txt' | 'srt' | 'vtt' | 'json'): string {
	switch (fmt) {
		case 'json':
			return JSON.stringify(doc, null, 2);
		case 'srt':
			return doc.segments
				.map((seg, i) =>
					`${i + 1}\n${ts(seg.start, true)} --> ${ts(seg.end, true)}\n${seg.text}\n`)
				.join('\n');
		case 'vtt':
			return (
				'WEBVTT\n\n' +
				doc.segments
					.map((seg, i) => `${i + 1}\n${ts(seg.start)} --> ${ts(seg.end)}\n${seg.text}\n`)
					.join('\n')
			);
		case 'txt':
		default:
			return doc.segments.map((s) => s.text).join('\n') + '\n';
	}
}

export function downloadTranscript(doc: TranscriptDocument, fmt: 'txt' | 'srt' | 'vtt' | 'json'): void {
	const blob = new Blob([serialize(doc, fmt)], { type: 'text/plain;charset=utf-8' });
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = `${(doc.source_file ?? 'transcript').replace(/\.[^.]+$/, '')}.${fmt}`;
	a.click();
	URL.revokeObjectURL(url);
}
