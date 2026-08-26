/**
 * TypeScript mirror of backend/ipc/schemas.py — SINGLE SOURCE OF TRUTH is Python.
 * RULE (spec §5): change schemas.py AND this file in the same commit.
 */

export type Stage =
	| 'queued' | 'preprocess' | 'vad' | 'transcribe' | 'align'
	| 'diarize' | 'postprocess' | 'export' | 'done' | 'error' | 'cancelled'
	| 'listening';

export type Device = 'auto' | 'cuda' | 'cpu';
export type ComputeType = 'int8' | 'int8_float16' | 'float16';

export interface TranscriptWord {
	start: number;
	end: number;
	text: string;
	confidence: number; // 0..1
	speaker?: string | null; // "Speaker 1"
	low_confidence: boolean;
}

export interface TranscriptSegment {
	start: number;
	end: number;
	text: string;
	words: TranscriptWord[];
	language?: string | null;
	draft: boolean;
}

export interface TranscriptDocument {
	schema_version: 1;
	source_file: string | null;
	duration_s: number;
	language: string; // ISO 639-1
	segments: TranscriptSegment[];
	vocabulary_applied: string[];
}

export interface Settings {
	model_size: string;
	device: Device;
	compute_type: ComputeType;
	denoise: boolean;
	diarize: boolean;
	min_speakers?: number | null; // 2..5
	max_speakers?: number | null;
	translate_to_english: boolean;
	custom_vocabulary: string[];
	vad_threshold: number; // 0..1
	export_formats: Array<'txt' | 'srt' | 'vtt' | 'json'>;
}

export const DEFAULT_SETTINGS: Settings = {
	model_size: 'medium',
	device: 'auto',
	compute_type: 'int8',
	denoise: false,
	diarize: false,
	min_speakers: null,
	max_speakers: null,
	translate_to_english: false,
	custom_vocabulary: [],
	vad_threshold: 0.5,
	export_formats: ['txt']
};

export interface JobStatus {
	event: 'job_status';
	job_id: string;
	stage: Stage;
	progress: number; // within current stage
	overall_progress: number; // weighted across stages
	message?: string | null;
}

/** One completed utterance from a live capture session, delivered via /events. */
export interface LiveTranscriptEvent {
	event: 'live_segment';
	session_id: string;
	start_s: number; // absolute offset in the live stream
	end_s: number;
	text: string;
}

export interface HealthReport {
	status: 'ok' | 'degraded';
	app_version: string;
	engines: Record<string, boolean>;
	models_present: string[];
	devices: Record<string, unknown>;
}
