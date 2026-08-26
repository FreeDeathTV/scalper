<script lang="ts">
	/** Placeholder — live mic lands in M5 (checklist). UI surface reserved so the
	 * layout doesn't reflow when streaming arrives. */
	let recording = $state(false);
</script>

<section>
	<h2>Live mic</h2>
	<button disabled onclick={() => (recording = false)}>
		Live transcription arrives in milestone M5
	</button>
	{#if recording}<span class="status-pill degraded">recording…</span>{/if}
</section>
