// Flat ESLint config (CI job runs `npm run lint`). Kept pragmatic for M0:
// TypeScript-ESLint recommended + Svelte parser, no stylistic rules (ruff
// analog for JS formatting comes later if the team wants it).
import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import svelte from 'eslint-plugin-svelte';

export default tseslint.config(
	js.configs.recommended,
	...tseslint.configs.recommended,
	...svelte.configs['flat/recommended'],
	{
		ignores: ['build/', '.svelte-kit/', 'dist/', 'src-tauri/', 'backend/', 'node_modules/']
	},
	{
		languageOptions: {
			globals: { ...globals.browser }
		}
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parserOptions: { parser: tseslint.parser }
		}
	},
	{
		rules: {
			'@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
			'no-console': 'warn'
		}
	}
);
