<script lang="ts">
	import { cancelJob, startBatchJob } from '$lib/api';
	import { appState } from '$lib/stores/appState.svelte';

	/** M0/M1 uses the Tauri dialog when available; browser dev falls back to path entry. */
	let manualPath = $state('');

	async function pickAndRun() {
		try {
			// @ts-expect-error tauri dialog plugin added in M0 wiring
			const { open } = await import('@tauri-apps/plugin-dialog');
			const selected = await open({ filters: [{ name: 'Audio', extensions: ['wav', 'mp3', 'm4a', 'flac', 'ogg'] }] });
			if (typeof selected === 'string') await run(selected);
		} catch {
			if (manualPath.trim()) await run(manualPath.trim());
		}
	}

	async function run(path: string) {
		appState.transcript = null;
		await startBatchJob(path, appState.settings);
	}

	async function cancel() {
		if (appState.job) await cancelJob(appState.job.job_id);
	}

	const busy = $derived(!!appState.job && !['done', 'error', 'cancelled'].includes(appState.job.stage));
</script>

<section>
	<h2>Import audio</h2>
	<button class="primary" onclick={pickAndRun} disabled={busy}>Choose file & transcribe</button>
	<label class="field">
		(or paste a path — dev fallback without Tauri dialog)
		<input type="text" bind:value={manualPath} placeholder="C:\audio\meeting.mp3" />
	</label>
	<button onclick={cancel} disabled={!busy}>Cancel job</button>
</section>
