/**
 * Browser mic → 16 kHz int16 PCM chunks for the N4 WebSocket uplink.
 * Starts only after mic_config.source === 'browser' and a user gesture.
 */

const TARGET_RATE = 16000

export function createBrowserMic({ onChunk, onError }) {
  let mediaStream = null
  let audioContext = null
  let workletNode = null
  let sourceNode = null
  let started = false
  let sending = false
  let chunkMs = 30
  let startPromise = null

  const chunkSamples = () => Math.max(1, Math.round((TARGET_RATE * chunkMs) / 1000))

  async function start(nextChunkMs = 30) {
    chunkMs = nextChunkMs
    if (started) {
      setSending(sending)
      return
    }
    if (startPromise) return startPromise
    startPromise = (async () => {
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            channelCount: 1,
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
          video: false,
        })
        audioContext = new AudioContext()
        if (audioContext.state === 'suspended') {
          await audioContext.resume()
        }
        await audioContext.audioWorklet.addModule('/pcm-worklet.js')
        sourceNode = audioContext.createMediaStreamSource(mediaStream)
        workletNode = new AudioWorkletNode(audioContext, 'pcm-capture', {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          channelCount: 1,
          processorOptions: {
            targetRate: TARGET_RATE,
            chunkSamples: chunkSamples(),
          },
        })
        workletNode.port.onmessage = (event) => {
          if (!sending) return
          onChunk?.(event.data)
        }
        // Keep the node in the graph so process() runs; mute so the mic isn't monitored.
        const mute = audioContext.createGain()
        mute.gain.value = 0
        sourceNode.connect(workletNode)
        workletNode.connect(mute)
        mute.connect(audioContext.destination)
        started = true
        workletNode.port.postMessage(sending ? 'start' : 'stop')
      } catch (err) {
        await stop()
        onError?.(err)
        throw err
      } finally {
        startPromise = null
      }
    })()
    return startPromise
  }

  function setSending(enabled) {
    sending = Boolean(enabled)
    if (workletNode) {
      workletNode.port.postMessage(sending ? 'start' : 'stop')
    }
    if (mediaStream) {
      for (const track of mediaStream.getAudioTracks()) {
        track.enabled = sending
      }
    }
  }

  async function stop() {
    sending = false
    started = false
    if (workletNode) {
      try {
        workletNode.port.postMessage('stop')
        workletNode.disconnect()
      } catch {
        /* ignore */
      }
      workletNode = null
    }
    if (sourceNode) {
      try {
        sourceNode.disconnect()
      } catch {
        /* ignore */
      }
      sourceNode = null
    }
    if (audioContext) {
      try {
        await audioContext.close()
      } catch {
        /* ignore */
      }
      audioContext = null
    }
    if (mediaStream) {
      for (const track of mediaStream.getTracks()) track.stop()
      mediaStream = null
    }
  }

  return { start, setSending, stop, get started() { return started } }
}
