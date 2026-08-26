<script lang="ts">
	import ProgressBar from '$lib/components/ProgressBar.svelte';
	import SettingsPanel from '$lib/components/SettingsPanel.svelte';
	import FileLoader from '$lib/components/FileLoader.svelte';
	import MicController from '$lib/components/MicController.svelte';
	import TranscriptEditor from '$lib/components/TranscriptEditor.svelte';
	import { getHealth, onJobEvent } from '$lib/api';
	import { appState } from '$lib/stores/appState.svelte';

		let unsub: (() => void) | null = null;

	$effect(() => {
		let active = true;
		getHealth()
			.then((h) => {
				appState.health = h;
			})
			.catch((e) => {
				appState.sidecarError = String(e);
			});
		onJobEvent((status) => {
			appState.job = status;
		}).then((u) => {
			if (active) unsub = u;
		});
		return () => {
			active = false;
			unsub?.();
			unsub = null;
		};
	});

	const stageText = $derived(appState.job ? `${appState.job.stage} — ${Math.round(appState.job.progress * 100)}%` : 'idle');
</script>

<header>
	<h1>Scalper Transcriber</h1>
	{#if appState.sidecarError}
		<span class="status-pill degraded">sidecar offline</span>
	{:else if appState.health}
		<span class="status-pill {appState.health.status}">
			{appState.health.status} · {appState.health.devices.cuda ? 'CUDA' : 'CPU'}
		</span>
	{/if}
</header>

<div class="workspace">
	<div class="panel">
		<FileLoader />
		<MicController />
		<SettingsPanel />
	</div>
	<div class="panel">
		<ProgressBar value={appState.job?.overall_progress ?? 0} label={stageText} />
		<TranscriptEditor />
	</div>
</div>
