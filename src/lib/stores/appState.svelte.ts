/** App state store (Svelte 5 runes). Persists settings to disk via localStorage
 * until the Tauri fs plugin lands in M0 (checklist item). */

import { DEFAULT_SETTINGS, type HealthReport, type JobStatus, type Settings, type TranscriptDocument } from '$lib/types/ipc';

const STORAGE_KEY = 'scalper.settings.v1';

function loadSettings(): Settings {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<Settings>) };
	} catch {
		/* corrupted storage falls back to defaults */
	}
	return { ...DEFAULT_SETTINGS };
}

class AppState {
	settings = $state<Settings>(loadSettings());
	health = $state<HealthReport | null>(null);
	job = $state<JobStatus | null>(null);
	transcript = $state<TranscriptDocument | null>(null);
	liveLines = $state<{ start_s: number; end_s: number; text: string }[]>([]);
	sidecarError = $state<string | null>(null);

	saveSettings(update: Partial<Settings>): void {
		this.settings = { ...this.settings, ...update };
		localStorage.setItem(STORAGE_KEY, JSON.stringify(this.settings));
	}
}

export const appState = new AppState();
