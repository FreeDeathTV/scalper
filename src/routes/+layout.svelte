<script lang="ts">
	import '../app.css';
	let { children } = $props();
</script>

<main class="shell">
	{@render children()}
</main>
