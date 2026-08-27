<script lang="ts">
	import { appState } from '$lib/stores/appState.svelte';
	import { waitForTranscript, uploadCapture } from '$lib/api';
	import { LiveTranscriber, SystemAudioRecorder } from '$lib/systemAudio';

	type Mode = 'idle' | 'recording' | 'live';
	let mode = $state<Mode>('idle');
	let error = $state<string | null>(null);
	let recorder: SystemAudioRecorder | null = null;
	let live: LiveTranscriber | null = null;
	let unsubLive: (() => void) | null = null;

	function normalizeOverlapToken(word: string): string {
		return word
			.normalize('NFKC')
			.toLocaleLowerCase()
			.replace(/[^\p{L}\p{N}]+/gu, '');
	}

	function withoutOverlap(text: string): string {
		const previous = appState.liveLines.at(-1)?.text ?? '';
		const previousWords = previous.trim().split(/\s+/);
		const currentWords = text.trim().split(/\s+/);
		const maxOverlap = Math.min(previousWords.length, currentWords.length);
		for (let count = maxOverlap; count >= 1; count--) {
			const suffix = previousWords
				.slice(-count)
				.map(normalizeOverlapToken)
				.join(' ');
			const prefix = currentWords
				.slice(0, count)
				.map(normalizeOverlapToken)
				.join(' ');
			if (suffix && suffix === prefix) {
				return currentWords.slice(count).join(' ').trim();
			}
		}
		return text.trim();
	}

	// Subscribe inside $effect so this only runs in the browser, never during
	// SSR/prerender: EventSource is a browser global (matches +page.svelte).
	// The sidecar broadcasts live_segment events for ALL sessions on the shared
	// /events SSE stream (stray/lingering connections included), so we must
	// filter by our own session id or a leftover session's audio bleeds into
	// this transcript.
	$effect(() => {
		let active = true;
		LiveTranscriber.subscribeEvents((sid, text, startS, draft) => {
			if (active && live && sid === live.sessionId) {
				if (!draft) {
					appState.liveLines = text.trim() ? [{ start_s: startS, text: text.trim() }] : [];
					return;
				}
				const cleaned = withoutOverlap(text);
				if (cleaned) appState.liveLines = [...appState.liveLines, { start_s: startS, text: cleaned }];
			}
		}).then((unsub) => {
			if (!active) unsub();
			else unsubLive = unsub;
		});
		return () => {
			active = false;
			unsubLive?.();
			unsubLive = null;
		};
	});

	async function fail(e: unknown): Promise<void> {
		error = e instanceof Error ? e.message : String(e);
		mode = 'idle';
	}

	async function startRecording(): Promise<void> {
		error = null;
		try {
			recorder = new SystemAudioRecorder();
			await recorder.start();
			mode = 'recording';
		} catch (e) {
			fail(e);
		}
	}

	async function stopRecording(): Promise<void> {
		if (!recorder) return;
		try {
			const wav = await recorder.stop();
			recorder = null;
			const jobId = await uploadCapture(wav, appState.settings);
			appState.transcript = await waitForTranscript(jobId);
			mode = 'idle';
		} catch (e) {
			fail(e);
		}
	}

	async function startLive(): Promise<void> {
		error = null;
		appState.liveLines = [];
		try {
			const settings =
				appState.settings.model_size !== 'base'
					? { ...appState.settings, model_size: 'base', device: 'cpu' as const }
					: appState.settings;
			live = new LiveTranscriber(settings);
			await live.start();
			mode = 'live';
		} catch (e) {
			fail(e);
		}
	}

	async function stopLive(): Promise<void> {
		if (!live) return;
		try {
			await live.stop();
			live = null;
			mode = 'idle';
		} catch (e) {
			fail(e);
		}
	}

	async function cancelLive(): Promise<void> {
		if (!live) return;
		try {
			await live.cancel();
			live = null;
			mode = 'idle';
		} catch (e) {
			fail(e);
		}
	}

</script>

<section>
	<h2>System audio</h2>
	<div class="row">
		{#if mode === 'idle'}
			<button onclick={startRecording}>⏺ Record &amp; transcribe</button>
			<button onclick={startLive}>▶ Live transcribe</button>
		{:else if mode === 'recording'}
			<button class="active" onclick={stopRecording}>⏹ Stop &amp; transcribe…</button>
		{:else}
			<button class="active" onclick={stopLive}>⏹ Stop live session</button>
			<button onclick={cancelLive}>✕ Cancel</button>
		{/if}
	</div>
	{#if error}<p class="error">{error}</p>{/if}
</section>

<style>
	.row { display: flex; gap: 0.5rem; }
	.active { background: var(--accent, #b33); color: #fff; }
	.error { color: #c0392b; font-size: 0.85rem; }
</style>
