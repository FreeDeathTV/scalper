<script lang="ts">
	import { appState } from '$lib/stores/appState.svelte';

	const h = $derived(appState.health);

	function bind<K extends keyof typeof appState.settings>(key: K) {
		return {
			get value() { return appState.settings[key]; },
			set value(v: (typeof appState.settings)[K]) { appState.saveSettings({ [key]: v } as never); }
		};
	}

	const diarize = bind('diarize');
	const denoise = bind('denoise');
	const translate = bind('translate_to_english');
	const vadThreshold = bind('vad_threshold');
	const modelSize = bind('model_size');

	const vocabText = $derived(appState.settings.custom_vocabulary.join(', '));
	const minSpeakers = $derived(appState.settings.min_speakers ?? 2);
	const maxSpeakers = $derived(appState.settings.max_speakers ?? 5);

	function updateVocab(raw: string) {
		appState.saveSettings({
			custom_vocabulary: raw.split(',').map((s) => s.trim()).filter(Boolean)
		});
	}
</script>

<section>
	<h2>Settings</h2>

	<label class="field">Model
		<select bind:value={modelSize.value}>
			<option value="large-v3">large-v3 (best)</option>
			<option value="medium">medium</option>
			<option value="small">small (faster)</option>
			<option value="base">base (live drafts)</option>
		</select>
	</label>
	{#if h && !h.engines['faster-whisper']}
		<p class="stage-label">⚠ faster-whisper not installed in sidecar venv</p>
	{/if}

	<label class="field"><input type="checkbox" bind:checked={denoise.value} /> Denoise (RNNoise)</label>
	<label class="field"><input type="checkbox" bind:checked={diarize.value} /> Detect speakers (diarization)</label>
	<label class="field"><input type="checkbox" bind:checked={translate.value} /> Translate → English</label>

	<label class="field">VAD threshold: {vadThreshold.value.toFixed(2)}
		<input type="range" min="0.1" max="0.9" step="0.05" bind:value={vadThreshold.value} />
	</label>

	<label class="field">Custom vocabulary (comma-separated)
		<input type="text" value={vocabText} oninput={(e) => updateVocab(e.currentTarget.value)} placeholder="Acme Corp, Silero, CTranslate2" />
	</label>

	<p class="stage-label">Speakers range {minSpeakers}–{maxSpeakers}</p>
</section>
