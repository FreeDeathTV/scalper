<script lang="ts">
	import { appState } from '$lib/stores/appState.svelte';

	const segments = $derived(appState.transcript?.segments ?? []);
	const liveLines = $derived(appState.liveLines);
	let copyState = $state<'idle' | 'copied' | 'failed'>('idle');

	const transcriptText = $derived(
		segments.length > 0
			? segments.map((segment) => segment.text).join('\n')
			: liveLines.map((line) => line.text).join('\n')
	);

	async function copyTranscript(): Promise<void> {
		try {
			await navigator.clipboard.writeText(transcriptText);
			copyState = 'copied';
		} catch {
			copyState = 'failed';
		}
	}

	function clearTranscript(): void {
		appState.transcript = null;
		appState.liveLines = [];
		copyState = 'idle';
	}

	function fmt(t: number): string {
		const m = Math.floor(t / 60);
		const s = Math.floor(t % 60);
		return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
	}

	function speakerOf(index: number): string | null {
		return segments[index]?.words.find((w) => w.speaker)?.speaker ?? null;
	}
</script>

<section aria-label="Transcript">
	<div class="heading-row">
		<h2>Transcript</h2>
		{#if transcriptText}
			<div class="actions">
				<button onclick={copyTranscript}>Copy</button>
				<button onclick={clearTranscript}>Clear</button>
			</div>
		{/if}
	</div>
	{#if copyState === 'copied'}<p class="stage-label">Copied to clipboard.</p>{/if}
	{#if copyState === 'failed'}<p class="error">Could not copy transcript to clipboard.</p>{/if}
	{#if segments.length === 0}
		{#if liveLines.length === 0}
			<p class="stage-label">No transcript yet — import a file to begin.</p>
		{:else}
			<div role="list">
				{#each liveLines as line, i (i)}
					<div class="segment-row" role="listitem">
						<span class="stage-label">{fmt(line.start_s)}</span>
						<span>{line.text}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<div role="list">
			{#each segments as seg, i (i)}
				<div class="segment-row" role="listitem" title={`${fmt(seg.start)} → ${fmt(seg.end)}`}>
					<span class="stage-label">{fmt(seg.start)}</span>
					{#if speakerOf(i)}
						<span class="speaker-tag">{speakerOf(i)}</span>
					{/if}
					<!-- words rendered with low-confidence highlighting per spec §7.4 -->
					{#each seg.words.length > 0 ? seg.words : [{ text: seg.text, low_confidence: false }] as w}
						<span class={w.low_confidence ? 'lc' : ''}>{w.text}</span>{' '}
					{/each}
				</div>
			{/each}
		</div>
	{/if}
</section>

<style>
	.heading-row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
	.actions { display: flex; gap: 0.4rem; }
	.error { color: #c0392b; font-size: 0.85rem; }
</style>
