<script lang="ts">
	import { downloadTranscript } from './exportUtils';
	import { appState } from '$lib/stores/appState.svelte';
	import type { TranscriptDocument } from '$lib/types/ipc';

	const doc = $derived(appState.transcript);

	function save(fmt: 'txt' | 'srt' | 'vtt' | 'json') {
		if (!doc) return;
		downloadTranscript(doc, fmt);
	}

	async function copyAll(): Promise<void> {
		if (!doc) return;
		await navigator.clipboard.writeText(
			doc.segments.map((s) => s.text).join('\n')
		);
	}
</script>

<details class="panel" open>
	<summary><strong>Export</strong></summary>
	<div style="display:flex; gap:0.5rem; flex-wrap:wrap; margin-top:0.5rem;">
		{#each ['txt', 'srt', 'vtt', 'json'] as fmt}
			<button onclick={() => save(fmt as 'txt')} disabled={!doc}>{fmt.toUpperCase()}</button>
		{/each}
		<button onclick={copyAll} disabled={!doc}>Copy all</button>
	</div>
	<p class="stage-label">Server-side export writes next to the source file; these buttons save a local copy.</p>
</details>
