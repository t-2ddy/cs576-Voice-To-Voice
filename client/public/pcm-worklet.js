/**
 * Downsample mic float32 to 16 kHz mono int16 and emit fixed-size PCM chunks.
 * Loaded via audioWorklet.addModule('/pcm-worklet.js').
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const opts = options.processorOptions || {}
    this.targetRate = opts.targetRate || 16000
    this.chunkSamples = opts.chunkSamples || 480
    this._ratio = sampleRate / this.targetRate
    this._acc = []
    this._sending = true
    this.port.onmessage = (e) => {
      if (e.data === 'stop') this._sending = false
      if (e.data === 'start') this._sending = true
    }
  }

  process(inputs) {
    if (!this._sending) return true
    const input = inputs[0] && inputs[0][0]
    if (!input || input.length === 0) return true

    for (let i = 0; i < input.length; i += 1) {
      this._acc.push(input[i])
    }

    const need = Math.ceil(this.chunkSamples * this._ratio)
    while (this._acc.length >= need) {
      const out = new Int16Array(this.chunkSamples)
      for (let o = 0; o < this.chunkSamples; o += 1) {
        const srcPos = o * this._ratio
        const i0 = Math.floor(srcPos)
        const frac = srcPos - i0
        const s0 = this._acc[i0]
        const s1 = this._acc[Math.min(i0 + 1, this._acc.length - 1)]
        const s = s0 + (s1 - s0) * frac
        const clamped = Math.max(-1, Math.min(1, s))
        out[o] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff
      }
      const consumed = Math.floor(this.chunkSamples * this._ratio)
      this._acc.splice(0, consumed)
      this.port.postMessage(out.buffer, [out.buffer])
    }
    return true
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor)
