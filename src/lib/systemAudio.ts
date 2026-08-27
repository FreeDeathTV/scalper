/**
 * System-audio (speaker loopback) capture â€” record-then-transcribe & live.
 *
 * Windows/WebView2 path: navigator.mediaDevices.getDisplayMedia({audio:true})
 * lets the user share system audio; we tap it through an AudioWorklet that
 * emits mono Float32 PCM already resampled to 16 kHz by the AudioContext.
 * Chromium-family browsers (including WebView2) honor sampleRate: 16000 here;
 * Firefox does not â€” surfaced as a readable error for the UI.
 */

import { readyBase } from '$lib/api';

const WORKLET_SRC = `
class PcmTap extends AudioWorkletProcessor {
	process(inputs) {
		const channel = inputs[0] && inputs[0][0];
		if (channel && channel.length) this.port.postMessage(channel.slice(0));
		return true;
	}
}
registerProcessor('pcm-tap', PcmTap);
`;

const TARGET_SR = 16_000;

export async function openSystemAudioStream(): Promise<MediaStream> {
	const stream = await navigator.mediaDevices.getDisplayMedia({
		video: true, // required by Chromium even for audio-only sharing
		audio: {
			echoCancellation: false,
			noiseSuppression: false,
			autoGainControl: false
		} as MediaTrackConstraints
	});
	stream.getVideoTracks().forEach((t) => t.stop()); // we only want audio
	if (stream.getAudioTracks().length === 0) {
		throw new Error('No audio track shared â€” tick "Share system audio" in the picker.');
	}
	return stream;
}

class PcmTapper {
	private ctx = new AudioContext({ sampleRate: TARGET_SR });
	private node: AudioWorkletNode | null = null;

	async start(stream: MediaStream, onChunk: (pcm: Float32Array) => void): Promise<void> {
		if (this.ctx.sampleRate !== TARGET_SR) {
			throw new Error(
				`Browser could not resample capture to ${TARGET_SR} Hz (got ${this.ctx.sampleRate}).`
			);
		}
		const url = URL.createObjectURL(new Blob([WORKLET_SRC], { type: 'text/javascript' }));
		try {
			await this.ctx.audioWorklet.addModule(url);
		} finally {
			URL.revokeObjectURL(url);
		}
		this.node = new AudioWorkletNode(this.ctx, 'pcm-tap');
		this.node.port.onmessage = (ev) => onChunk(ev.data as Float32Array);
		await this.ctx.resume();
		this.ctx.createMediaStreamSource(stream).connect(this.node);
	}

	stop(): void {
		this.node?.port.close();
		this.node?.disconnect();
		void this.ctx.close();
	}
}

/** Encode concatenated PCM frames as a RIFF/WAVE blob (16-bit PCM). */
export function encodeWav(frames: Float32Array[], sampleRate = TARGET_SR): Blob {
	const total = frames.reduce((n, f) => n + f.length, 0);
	const data = new Int16Array(total);
	let o = 0;
	for (const f of frames) {
		for (let i = 0; i < f.length; i++, o++) {
			const s: number = Math.max(-1, Math.min(1, f[i] ?? 0));
			data[o] = s < 0 ? s * 0x8000 : s * 0x7fff;
		}
	}
	const buf = new ArrayBuffer(44 + data.byteLength);
	const v = new DataView(buf);
	const ascii = (off: number, s: string) =>
		[...s].forEach((c, i) => v.setUint8(off + i, c.charCodeAt(0)));
	ascii(0, 'RIFF');
	v.setUint32(4, 36 + data.byteLength, true);
	ascii(8, 'WAVE');
	ascii(12, 'fmt ');
	v.setUint32(16, 16, true);
	v.setUint16(20, 1, true); // PCM
	v.setUint16(22, 1, true); // mono
	v.setUint32(24, sampleRate, true);
	v.setUint32(28, sampleRate * 2, true); // byte rate
	v.setUint16(32, 2, true); // block align
	v.setUint16(34, 16, true); // bits
	ascii(36, 'data');
	v.setUint32(40, data.byteLength, true);
	new Uint8Array(buf, 44).set(new Uint8Array(data.buffer));
	return new Blob([buf], { type: 'audio/wav' });
}

/** Record system audio locally; stop() returns the WAV for /capture/upload. */
export class SystemAudioRecorder {
	private frames: Float32Array[] = [];
	private tapper: PcmTapper | null = null;
	private stream: MediaStream | null = null;

	async start(): Promise<void> {
		this.stream = await openSystemAudioStream();
		this.tapper = new PcmTapper();
		await this.tapper.start(this.stream, (pcm) => this.frames.push(pcm));
	}

	async stop(): Promise<Blob> {
		this.tapper?.stop();
		this.stream?.getTracks().forEach((t) => t.stop());
		const wav = encodeWav(this.frames);
		this.frames = [];
		return wav;
	}
}

/** Live mode: stream PCM over WS; finished utterances arrive via SSE events. */
export class LiveTranscriber {
	private tapper: PcmTapper | null = null;
	private stream: MediaStream | null = null;
	private ws: WebSocket | null = null;
	private pending: Float32Array[] = [];
	private pendingSamples = 0;
	private flushTimer: ReturnType<typeof setInterval> | null = null;

	/** Set once the server acks the init frame; used by callers to filter SSE
	 * events so a stale/lingering session's utterances never leak into a new
	 * one's transcript. */
	sessionId: string | null = null;

	constructor(private settingsJson: unknown) {}

	async start(): Promise<void> {
		this.stream = await openSystemAudioStream();
		this.ws = new WebSocket(`${(await readyBase()).replace('http', 'ws')}/ws/live`);
		this.ws.binaryType = 'arraybuffer';
		await new Promise<void>((resolve, reject) => {
			if (!this.ws) return resolve();
			this.ws.onopen = () => resolve();
			this.ws.onerror = () => reject(new Error('sidecar live socket refused'));
		});
		this.ws!.send(JSON.stringify({ settings: this.settingsJson }));

		this.sessionId = await new Promise<string>((resolve, reject) => {
			if (!this.ws) return reject(new Error('socket closed before ack'));
			const timer = setTimeout(() => reject(new Error('sidecar did not ack live session')), 5000);
			this.ws.onmessage = (ev) => {
				clearTimeout(timer);
				try {
					const data = JSON.parse(ev.data as string) as { session_id?: string };
					if (data.session_id) resolve(data.session_id);
					else reject(new Error('sidecar ack missing session_id'));
				} catch (e) {
					reject(e instanceof Error ? e : new Error(String(e)));
				}
			};
		});
		this.ws!.onmessage = null;

		this.tapper = new PcmTapper();
		await this.tapper.start(this.stream, (pcm) => this.enqueue(pcm));
		this.flushTimer = setInterval(() => this.flush(), 250); // ~4 batches/s
	}

	private enqueue(pcm: Float32Array): void {
		this.pending.push(pcm);
		this.pendingSamples += pcm.length;
		if (this.pendingSamples >= TARGET_SR) this.flush(); // â‰¥1s backpressure guard
	}

	private flush(): void {
		if (!this.pending.length || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
		const merged = new Float32Array(this.pendingSamples);
		let o = 0;
		for (const p of this.pending) {
			merged.set(p, o);
			o += p.length;
		}
		this.pending = [];
		this.pendingSamples = 0;
		this.ws.send(merged.buffer);
	}

	/** Wire SSE-side delivery of finished utterances (call once at mount). */
	static async subscribeEvents(
		handler: (sessionId: string, text: string, startS: number, endS: number, draft: boolean) => void
	): Promise<() => void> {
		// Defensive: never touch browser-only globals during SSR/prerender.
		if (typeof EventSource === 'undefined') return () => {};
		const es = new EventSource(`${await readyBase()}/events`);
		es.onmessage = (ev) => {
			try {
				const data = JSON.parse(ev.data) as { event?: string };
				if (data.event === 'live_segment') {
					const seg = data as unknown as {
						session_id: string;
						text: string;
						start_s: number;
						end_s: number;
						draft?: boolean;
					};
					handler(seg.session_id, seg.text, seg.start_s, seg.end_s, seg.draft !== false);
				}
			} catch {
				/* ignore malformed frames */
			}
		};
		return () => es.close();
	}

	async stop(): Promise<{ text: string; endS: number } | null> {
		if (this.flushTimer) clearInterval(this.flushTimer);
		this.flush();
		this.tapper?.stop();
		this.stream?.getTracks().forEach((t) => t.stop());
		let finalResult: { text: string; endS: number } | null = null;
		await new Promise<void>((resolve) => {
			if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return resolve();
			this.ws.onmessage = (ev) => {
				try {
					const data = JSON.parse(ev.data as string) as { final_text?: string; final_end_s?: number };
					if (data.final_text && typeof data.final_end_s === 'number') {
						finalResult = { text: data.final_text, endS: data.final_end_s };
					}
				} catch {
					/* ignore non-JSON completion frames */
				}
			};
			this.ws.onclose = () => resolve();
			this.ws.send(JSON.stringify({ action: 'stop' }));
		});
		this.ws = null;
		return finalResult;
	}

	async cancel(): Promise<void> {
		if (this.flushTimer) clearInterval(this.flushTimer);
		this.tapper?.stop();
		this.stream?.getTracks().forEach((t) => t.stop());
		await new Promise<void>((resolve) => {
			if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return resolve();
			this.ws.onclose = () => resolve();
			this.ws.send(JSON.stringify({ action: 'cancel' }));
			setTimeout(resolve, 1000);
		});
		this.ws = null;
	}
}
