<script lang="ts">
	let { value, label = '' }: { value: number; label?: string } = $props();
	const pct = $derived(Math.round(value * 100));
</script>

<div class="progress-track" role="progressbar" aria-valuenow={pct} aria-valuemin="0" aria-valuemax="100">
	<div class="progress-fill" style="width: {pct}%"></div>
</div>
<p class="stage-label">{label}</p>
