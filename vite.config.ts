import { defineConfig } from 'vite';
import { sveltekit } from '@sveltejs/kit/vite';

const isTauri = process.env.TAURI_ENV_PLATFORM !== undefined;

export default defineConfig({
	plugins: [sveltekit()],
	clearScreen: false,
	server: {
		// Frontend dev server. The Python sidecar (backend/main.py) picks its own
		// loopback port and reports it to the UI at startup (spec §5 /health).
		port: 1420,
		strictPort: true,
		watch: {
			// Never rebuild for shell/backend changes (they're separate processes)
			ignored: ['**/src-tauri/**', '**/backend/**']
		}
	},
	envPrefix: ['VITE_', 'TAURI_ENV_'],
	build: {
		target: 'es2021',
		minify: !isTauri || !process.env.TAURI_ENV_DEBUG ? 'esbuild' : false,
		sourcemap: !!process.env.TAURI_ENV_DEBUG
	}
});
