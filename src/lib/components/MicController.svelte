<script lang="ts">
	import { appState } from '$lib/stores/appState.svelte';
	import { waitForTranscript, uploadCapture } from '$lib/api';
	import { LiveTranscriber, SystemAudioRecorder } from '$lib/systemAudio';

	type Mode = 'idle' | 'recording' | 'live';
	let mode = $state<Mode>('idle');
	let error = $state<string | null>(null);
	let liveLines = $state<{ start_s: number; text: string }[]>([]);
	let recorder: SystemAudioRecorder | null = null;
	let live: LiveTranscriber | null = null;
	let unsubLive: (() => void) | null = null;

	// Subscribe inside $effect so this only runs in the browser, never during
	// SSR/prerender: EventSource is a browser global (matches +page.svelte).
	$effect(() => {
		unsubLive = LiveTranscriber.subscribeEvents((_sid, text, startS) => {
			liveLines = [...liveLines, { start_s: startS, text }];
		});
		return () => {
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
		liveLines = [];
		try {
			live = new LiveTranscriber(appState.settings);
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

	const fmtTime = (s: number): string => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
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
		{/if}
	</div>
	{#if error}<p class="error">{error}</p>{/if}
	{#if liveLines.length > 0}
		<div class="live-out">
			{#each liveLines as line, i (i)}
				<p><span class="ts">{fmtTime(line.start_s)}</span> {line.text}</p>
			{/each}
		</div>
	{/if}
</section>

<style>
	.row { display: flex; gap: 0.5rem; }
	.active { background: var(--accent, #b33); color: #fff; }
	.error { color: #c0392b; font-size: 0.85rem; }
	.live-out {
		max-height: 12rem;
		overflow-y: auto;
		font-size: 0.9rem;
		border-top: 1px solid #ddd;
		margin-top: 0.5rem;
		padding-top: 0.4rem;
	}
	.ts { color: #888; font-variant-numeric: tabular-nums; margin-right: 0.4rem; }
</style>

