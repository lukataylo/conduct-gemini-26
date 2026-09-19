const CAPTURE_RATE = 16000;
const PLAY_RATE = 24000;

function resample(input: Float32Array, fromRate: number, toRate: number): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const n = Math.floor(input.length / ratio);
  if (n <= 0) return new Float32Array(0);
  const out = new Float32Array(n);
  const last = input.length - 1;
  for (let i = 0; i < n; i++) {
    const src = i * ratio;
    const i0 = Math.min(Math.floor(src), last);
    const i1 = Math.min(i0 + 1, last);
    const frac = src - i0;
    out[i] = input[i0] * (1 - frac) + input[i1] * frac;
  }
  return out;
}

function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function int16ToFloat(buf: ArrayBuffer): Float32Array {
  const even = buf.byteLength - (buf.byteLength % 2);
  if (!even) return new Float32Array(0);
  const samples = new Int16Array(buf, 0, even / 2);
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) out[i] = samples[i] / 0x8000;
  return out;
}

function pcmBuffer(samples: Int16Array): ArrayBuffer {
  const out = new ArrayBuffer(samples.byteLength);
  new Uint8Array(out).set(new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength));
  return out;
}

export async function startMic(
  onPcm: (buf: ArrayBuffer) => void,
  onLevel: (n: number) => void,
): Promise<{ stop: () => void }> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new Ctx();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const mute = ctx.createGain();
  mute.gain.value = 0;
  proc.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0);
    let sum = 0;
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
    onLevel(Math.min(1, Math.sqrt(sum / input.length) * 6));
    const pcm = floatToInt16(resample(input, ctx.sampleRate, CAPTURE_RATE));
    if (pcm.length) onPcm(pcmBuffer(pcm));
  };
  src.connect(proc);
  proc.connect(mute);
  mute.connect(ctx.destination);
  if (ctx.state === "suspended") void ctx.resume();
  return {
    stop: () => {
      proc.onaudioprocess = null;
      proc.disconnect();
      src.disconnect();
      mute.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      onLevel(0);
    },
  };
}

export function createPlayer(): { push(buf: ArrayBuffer): void; reset(): void; close(): void } {
  const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  let ctx: AudioContext | null = null;
  let gain: GainNode | null = null;
  let nextAt = 0;
  let closed = false;
  const sources = new Set<AudioBufferSourceNode>();

  const ensure = (): AudioContext | null => {
    if (closed) return null;
    if (!ctx || ctx.state === "closed") {
      ctx = new Ctx({ sampleRate: PLAY_RATE });
      gain = ctx.createGain();
      gain.connect(ctx.destination);
      nextAt = 0;
    }
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  };

  const stopSources = () => {
    for (const src of sources) {
      try { src.stop(); } catch { /* already ended */ }
    }
    sources.clear();
    nextAt = 0;
  };

  return {
    push(buf: ArrayBuffer) {
      const ac = ensure();
      if (!ac || !gain || !buf.byteLength) return;
      const floats = resample(int16ToFloat(buf), PLAY_RATE, ac.sampleRate);
      if (!floats.length) return;
      const audio = ac.createBuffer(1, floats.length, ac.sampleRate);
      audio.getChannelData(0).set(floats);
      const src = ac.createBufferSource();
      src.buffer = audio;
      src.connect(gain);
      src.onended = () => sources.delete(src);
      sources.add(src);
      const now = ac.currentTime;
      if (nextAt < now) nextAt = now;
      src.start(nextAt);
      nextAt += audio.duration;
    },
    reset() {
      stopSources();
    },
    close() {
      closed = true;
      stopSources();
      if (ctx && ctx.state !== "closed") void ctx.close();
      ctx = null;
      gain = null;
    },
  };
}
