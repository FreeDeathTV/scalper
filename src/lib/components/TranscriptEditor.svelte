<script lang="ts">
	import { appState } from '$lib/stores/appState.svelte';

	const segments = $derived(appState.transcript?.segments ?? []);

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
	<h2>Transcript</h2>
	{#if segments.length === 0}
		<p class="stage-label">No transcript yet — import a file to begin.</p>
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
						<span class:w.low_confidence>{w.text}</span>{' '}
					{/each}
				</div>
			{/each}
		</div>
	{/if}
</section>
