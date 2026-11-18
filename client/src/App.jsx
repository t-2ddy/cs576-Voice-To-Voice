import { useEffect, useRef, useState } from 'react'
import { createBrowserMic } from './browserMic'
import './App.css'

const BG_DIR = '/images/background'
const FRIEREN_ART = '/images/frieren/pixFrieren.gif'

const TASKBAR_HEIGHT = 40
const MIN_WIN_W = 320
const MIN_WIN_H = 280

const RESIZE_HANDLES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

const HEALTH_POLL_MS = 1000
const HEALTH_TIMEOUT_MS = 1500
const CONNECT_TIMEOUT_MS = 4000

const STATUS_LABELS = {
  listening: 'Listening...',
  thinking: 'Thinking...',
  speaking: 'Speaking...',
  ready: 'Ready',
  error: 'Error',
  offline: 'Offline (backend not running)',
  connecting: 'Connecting...',
}

/** Decode GIF once and cache a PNG of the first frame. */
let frierenStillPromise = null
function loadFrierenStill() {
  if (!frierenStillPromise) {
    frierenStillPromise = new Promise((resolve) => {
      const img = new Image()
      img.onload = () => {
        try {
          const canvas = document.createElement('canvas')
          canvas.width = img.naturalWidth || img.width
          canvas.height = img.naturalHeight || img.height
          const ctx = canvas.getContext('2d')
          if (!ctx) {
            resolve(FRIEREN_ART)
            return
          }
          ctx.drawImage(img, 0, 0)
          resolve(canvas.toDataURL('image/png'))
        } catch {
          resolve(FRIEREN_ART)
        }
      }
      img.onerror = () => resolve(FRIEREN_ART)
      img.src = FRIEREN_ART
    })
  }
  return frierenStillPromise
}

function useFrierenStill() {
  const [stillSrc, setStillSrc] = useState(null)
  useEffect(() => {
    let cancelled = false
    loadFrierenStill().then((src) => {
      if (!cancelled) setStillSrc(src)
    })
    return () => {
      cancelled = true
    }
  }, [])
  return stillSrc
}

function TitleButtons() {
  return (
    <div className="title-buttons" aria-hidden="true">
      <button type="button" className="tb tb-min" tabIndex={-1} title="Minimize">
        <span />
      </button>
      <button type="button" className="tb tb-max" tabIndex={-1} title="Maximize">
        <span />
      </button>
      <button type="button" className="tb tb-close" tabIndex={-1} title="Close">
        <span />
      </button>
    </div>
  )
}

const PORTRAIT_FADE_OUT_MS = 320

/** Animated GIF while speaking; frozen first frame once the fade-out finishes. */
function FrierenPortrait({ playing, className, alt }) {
  const stillSrc = useFrierenStill()
  const [showGif, setShowGif] = useState(playing)

  useEffect(() => {
    if (playing) {
      setShowGif(true)
      return
    }
    const timer = setTimeout(() => setShowGif(false), PORTRAIT_FADE_OUT_MS)
    return () => clearTimeout(timer)
  }, [playing])

  const src = showGif ? FRIEREN_ART : stillSrc || FRIEREN_ART

  return (
    <img
      className={`${className}${playing ? ' is-speaking' : ''}`}
      src={src}
      alt={alt}
    />
  )
}

function Taskbar() {
  const frierenStill = useFrierenStill()
  const icons = [
    { src: `${BG_DIR}/icon_home.png`, label: 'Start' },
    { src: `${BG_DIR}/icon_internet_explorer.png`, label: 'Internet Explorer' },
    { src: `${BG_DIR}/icon_file_explorer.png`, label: 'File Explorer' },
    { src: frierenStill, label: 'Frieren - Grimoire' },
  ]

  return (
    <nav className="taskbar" aria-label="Windows taskbar">
      <div className="taskbar-icons">
        {icons.map((icon) => (
          <button
            key={icon.label}
            type="button"
            className="taskbar-icon"
            title={icon.label}
            aria-label={icon.label}
            tabIndex={-1}
            onClick={(e) => e.preventDefault()}
          >
            {icon.src ? (
              <img src={icon.src} alt="" width="32" height="32" />
            ) : null}
          </button>
        ))}
      </div>
    </nav>
  )
}

function clampPos(x, y, width, height) {
  const maxX = Math.max(0, window.innerWidth - width)
  const maxY = Math.max(0, window.innerHeight - TASKBAR_HEIGHT - height)
  return {
    x: Math.min(Math.max(0, x), maxX),
    y: Math.min(Math.max(0, y), maxY),
  }
}

function clampSize(width, height) {
  const maxW = Math.max(MIN_WIN_W, window.innerWidth)
  const maxH = Math.max(MIN_WIN_H, window.innerHeight - TASKBAR_HEIGHT)
  return {
    width: Math.min(Math.max(MIN_WIN_W, width), maxW),
    height: Math.min(Math.max(MIN_WIN_H, height), maxH),
  }
}

// Background tabs throttle main-thread timers to ~1/min; worker timers keep firing,
// so reconnect retries still land while the user is in another window.
function createWorkerTimer() {
  try {
    const src =
      'let t; onmessage = (e) => { clearTimeout(t); if (e.data >= 0) t = setTimeout(() => postMessage(0), e.data) }'
    const url = URL.createObjectURL(new Blob([src], { type: 'text/javascript' }))
    const worker = new Worker(url)
    URL.revokeObjectURL(url)
    let callback = null
    worker.onmessage = () => callback?.()
    return {
      set(fn, ms) {
        callback = fn
        worker.postMessage(ms)
      },
      clear() {
        callback = null
        worker.postMessage(-1)
      },
      dispose() {
        worker.terminate()
      },
    }
  } catch {
    let t
    return {
      set(fn, ms) {
        clearTimeout(t)
        t = setTimeout(fn, ms)
      },
      clear() {
        clearTimeout(t)
      },
      dispose() {
        clearTimeout(t)
      },
    }
  }
}

function useChatBridge() {
  const [line, setLine] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [statusDetail, setStatusDetail] = useState('')
  // Sticky until the next user turn; server "listening" right after an error
  // would otherwise hide it almost instantly.
  const [lastError, setLastError] = useState('')
  const audioRef = useRef(null)
  const objectUrlRef = useRef(null)
  const pendingAudioRef = useRef(null)
  const audioUnlockedRef = useRef(false)

  useEffect(() => {
    let ws = null
    let closed = false
    let probing = false
    let connectStartedAt = 0
    let stream = null
    let micSource = 'local'
    let micChunkMs = 30
    let micStartedMsg = false
    let wantMicSend = false
    let lastServerStatus = ''
    const retryTimer = createWorkerTimer()

    const browserMic = createBrowserMic({
      onChunk: (buffer) => {
        if (!wantMicSend || !ws || ws.readyState !== WebSocket.OPEN) return
        if (!micStartedMsg) {
          ws.send(
            JSON.stringify({
              type: 'mic_start',
              format: 'pcm_s16le',
              rate: 16000,
              chunk_ms: micChunkMs,
            }),
          )
          micStartedMsg = true
        }
        ws.send(buffer)
      },
      onError: (err) => {
        const detail = err?.message || 'Microphone permission denied'
        setStatus('error')
        setStatusDetail(detail)
        setLastError(detail)
      },
    })

    const syncMicSending = (statusValue) => {
      // Half-duplex: only uplink while the server is listening (drops during thinking/speaking).
      wantMicSend = micSource === 'browser' && statusValue === 'listening'
      browserMic.setSending(wantMicSend)
    }

    const ensureBrowserMic = () => {
      if (micSource !== 'browser' || closed) return
      void browserMic.start(micChunkMs).then(() => {
        syncMicSending(lastServerStatus)
      })
    }

    const stopAudio = () => {
      stream = null
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current = null
      }
      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current)
        objectUrlRef.current = null
      }
    }

    const fail = (detail) => {
      setStatus('error')
      setStatusDetail(detail)
      setLastError(detail)
    }

    // Tells the server it can start listening again (it mutes the mic while we play).
    // `streamId` tags reports for N3 streams; the server ignores untagged ones mid-stream.
    const sendPlaybackDone = (streamId) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'playback_done', ...(streamId ? { stream: streamId } : {}) }))
      }
    }

    // N1 latency: when the clip arrived and when sound actually started (Date.now()
    // shares the server's clock only when both run on the same machine).
    const sendPlaybackStarted = (recvTs, blocked, streamId) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({
            type: 'playback_started',
            recv_ts: recvTs,
            play_ts: Date.now(),
            ...(blocked ? { blocked: true } : {}),
            ...(streamId ? { stream: streamId } : {}),
          }),
        )
      }
    }

    const unlockAudio = () => {
      if (audioUnlockedRef.current) return
      audioUnlockedRef.current = true
      try {
        const silent = new Audio(
          'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=',
        )
        silent.volume = 0.01
        void silent.play().catch(() => {})
      } catch {
        /* ignore unlock failures; gesture still counts for later play() */
      }
      ensureBrowserMic()
    }

    const base64ToBytes = (b64) => {
      const binary = atob(b64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i)
      }
      return bytes
    }

    // Shared by full clips and streams. `info.recvTs` is when the first audio
    // bytes arrived; `info.blocked` marks a play that waited for a click;
    // `info.id` is the stream id (undefined for full clips).
    const attachPlaybackHandlers = (audio, info) => {
      audio.addEventListener(
        'playing',
        () => sendPlaybackStarted(info.recvTs, info.blocked, info.id),
        { once: true },
      )
      audio.onended = () => {
        stopAudio()
        pendingAudioRef.current = null
        setStatus((s) => (s === 'speaking' ? 'ready' : s))
        sendPlaybackDone(info.id)
      }
      audio.onerror = () => {
        stopAudio()
        pendingAudioRef.current = null
        fail('Audio playback failed')
        sendPlaybackDone(info.id)
      }
    }

    // On autoplay refusal, `replay` is kept and run on the next click/key.
    const startPlayback = (audio, info, replay) => {
      void audio.play().catch((err) => {
        if (audioRef.current !== audio) return
        const autoplayBlocked =
          err?.name === 'NotAllowedError' ||
          /not allowed|user.*denied|interact/i.test(err?.message || '')
        if (autoplayBlocked) {
          pendingAudioRef.current = replay
          setStatus('error')
          setStatusDetail('Click the window to enable audio')
          setLastError('Click the window to enable audio')
          return
        }
        stopAudio()
        fail(err?.message || 'Audio play blocked')
        sendPlaybackDone(info.id)
      })
    }

    // `bytes` is an ArrayBuffer (binary WS frame), Uint8Array (decoded base64),
    // or an array of chunks (stream fallback, with its stream `id`).
    const playMp3 = (bytes, recvTs = Date.now(), blocked = false, id = undefined) => {
      stopAudio()
      pendingAudioRef.current = null
      const info = { recvTs, blocked, id }
      try {
        const blob = new Blob(Array.isArray(bytes) ? bytes : [bytes], { type: 'audio/mpeg' })
        const url = URL.createObjectURL(blob)
        objectUrlRef.current = url
        const audio = new Audio(url)
        audioRef.current = audio
        setStatus('speaking')
        attachPlaybackHandlers(audio, info)
        startPlayback(audio, info, () => playMp3(bytes, recvTs, true, id))
      } catch (err) {
        stopAudio()
        fail(err?.message || 'Invalid audio payload')
        sendPlaybackDone(id)
      }
    }

    // N3 streamed replies: audio_start, binary MP3 chunks, audio_end. MediaSource
    // plays chunks as they arrive; without MP3 support in MSE (some Firefox
    // builds) the chunks are collected and played as one clip at audio_end.
    const startStream = (id) => {
      stopAudio()
      pendingAudioRef.current = null
      const s = { id, recvTs: null, blocked: false, chunks: [], queue: [], ended: false }
      stream = s
      const mseOk = typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported('audio/mpeg')
      if (!mseOk) return
      try {
        const ms = new MediaSource()
        const url = URL.createObjectURL(ms)
        objectUrlRef.current = url
        const audio = new Audio(url)
        audioRef.current = audio
        s.ms = ms
        s.audio = audio
        attachPlaybackHandlers(audio, s)
        ms.addEventListener(
          'sourceopen',
          () => {
            if (stream !== s) return
            try {
              s.sb = ms.addSourceBuffer('audio/mpeg')
              s.sb.mode = 'sequence'
              s.sb.addEventListener('updateend', () => pumpStream(s))
              pumpStream(s)
            } catch (err) {
              fallBackToClip(s, err)
            }
          },
          { once: true },
        )
      } catch (err) {
        fallBackToClip(s, err)
      }
    }

    const fallBackToClip = (s, err) => {
      console.warn('MediaSource playback unavailable, playing at audio_end', err)
      if (audioRef.current === s.audio) stopAudio()
      s.ms = s.sb = s.audio = null
      stream = s
      if (s.ended) finishStream(s)
    }

    const pumpStream = (s) => {
      if (stream !== s || !s.sb || s.sb.updating) return
      if (s.queue.length) {
        try {
          s.sb.appendBuffer(s.queue.shift())
        } catch (err) {
          fallBackToClip(s, err)
          return
        }
        if (!s.playRequested) {
          s.playRequested = true
          setStatus('speaking')
          startPlayback(s.audio, s, () => {
            s.blocked = true
            if (audioRef.current === s.audio) startPlayback(s.audio, s, () => {})
          })
        }
        return
      }
      if (s.ended && s.ms.readyState === 'open') s.ms.endOfStream()
    }

    const onStreamChunk = (s, data, recvTs) => {
      if (s.recvTs === null) s.recvTs = recvTs
      s.chunks.push(data)
      if (s.sb) {
        s.queue.push(data)
        pumpStream(s)
      } else if (s.ms) {
        s.queue.push(data)
      }
    }

    const finishStream = (s) => {
      s.ended = true
      if (s.ms) {
        pumpStream(s)
        return
      }
      stream = null
      if (s.chunks.length) {
        playMp3(s.chunks, s.recvTs ?? Date.now(), false, s.id)
      } else {
        sendPlaybackDone(s.id)
      }
    }

    const isLive = () =>
      ws &&
      (ws.readyState === WebSocket.OPEN ||
        (ws.readyState === WebSocket.CONNECTING &&
          Date.now() - connectStartedAt < CONNECT_TIMEOUT_MS))

    const dropSocket = () => {
      if (!ws) return
      const old = ws
      ws = null
      micStartedMsg = false
      wantMicSend = false
      browserMic.setSending(false)
      old.onopen = old.onmessage = old.onclose = old.onerror = null
      try {
        old.close()
      } catch {
        /* already closed */
      }
    }

    const scheduleProbe = (ms = HEALTH_POLL_MS) => {
      if (!closed) retryTimer.set(probe, ms)
    }

    const goOffline = () => {
      setStatus('offline')
      setStatusDetail('Backend not running')
    }

    // Probe over plain HTTP first: browsers delay repeated failed WebSocket
    // handshakes to one endpoint, which can stall reconnects for ~60s.
    async function probe() {
      if (closed || probing || isLive()) return
      if (ws) dropSocket()
      probing = true
      const ctrl = new AbortController()
      const abortTimer = setTimeout(() => ctrl.abort(), HEALTH_TIMEOUT_MS)
      let up = false
      try {
        const res = await fetch('/bridge-health', { cache: 'no-store', signal: ctrl.signal })
        up = res.ok
      } catch {
        up = false
      } finally {
        clearTimeout(abortTimer)
        probing = false
      }
      if (closed || isLive()) return
      if (up) {
        openSocket()
      } else {
        goOffline()
        scheduleProbe()
      }
    }

    const openSocket = () => {
      setStatus((s) =>
        s === 'ready' || s === 'listening' || s === 'thinking' || s === 'speaking'
          ? s
          : 'connecting',
      )
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const sock = new WebSocket(`${proto}://${window.location.host}/ws`)
      sock.binaryType = 'arraybuffer'
      ws = sock
      connectStartedAt = Date.now()
      retryTimer.set(() => {
        if (ws === sock && sock.readyState === WebSocket.CONNECTING) {
          dropSocket()
          goOffline()
          probe()
        }
      }, CONNECT_TIMEOUT_MS)

      sock.onopen = () => {
        retryTimer.clear()
        setStatus('ready')
        setStatusDetail('')
      }

      sock.onmessage = (event) => {
        const recvTs = Date.now()
        // Binary frames are chunks of the current stream (N3), or the whole MP3
        // announced by a preceding `audio` header.
        if (event.data instanceof ArrayBuffer) {
          if (stream && !stream.ended) onStreamChunk(stream, event.data, recvTs)
          else playMp3(event.data, recvTs)
          return
        }
        let data
        try {
          data = JSON.parse(event.data)
        } catch {
          return
        }
        if (data.type === 'mic_config') {
          micSource = data.source === 'browser' ? 'browser' : 'local'
          micChunkMs = Number(data.chunk_ms) > 0 ? Number(data.chunk_ms) : 30
          micStartedMsg = false
          if (micSource === 'browser' && audioUnlockedRef.current) {
            ensureBrowserMic()
          } else if (micSource !== 'browser') {
            wantMicSend = false
            browserMic.setSending(false)
            void browserMic.stop()
          }
          syncMicSending(lastServerStatus)
        } else if (data.type === 'chat' && data.text) {
          if (data.who === 'you') setLastError('')
          setLine({ who: data.who === 'you' ? 'you' : 'frieren', text: data.text })
        } else if (data.type === 'audio_start') {
          startStream(data.stream)
        } else if (data.type === 'audio_end') {
          if (stream && stream.id === data.stream) finishStream(stream)
        } else if (data.type === 'audio') {
          if (data.data) playMp3(base64ToBytes(data.data), recvTs)
          else stream = null
        } else if (data.type === 'status' && data.value) {
          // Don't let a quick server "ready" clobber local speaking while audio plays.
          if (data.value === 'ready' && audioRef.current && !audioRef.current.paused) {
            return
          }
          lastServerStatus = data.value
          setStatus(data.value)
          setStatusDetail(data.detail || '')
          if (data.value === 'error') setLastError(data.detail || 'Unknown error')
          syncMicSending(data.value)
          if (data.value === 'listening' && micSource === 'browser') {
            ensureBrowserMic()
          }
        }
      }

      sock.onclose = () => {
        if (closed || ws !== sock) return
        ws = null
        retryTimer.clear()
        goOffline()
        scheduleProbe()
      }

      sock.onerror = () => {
        sock.close()
      }
    }

    const reconnectSoon = () => {
      if (closed || isLive()) return
      retryTimer.clear()
      probe()
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') reconnectSoon()
    }

    const onUserGesture = () => {
      unlockAudio()
      const replay = pendingAudioRef.current
      if (replay) {
        pendingAudioRef.current = null
        replay()
      }
    }

    probe()
    window.addEventListener('focus', reconnectSoon)
    document.addEventListener('visibilitychange', onVisibility)
    window.addEventListener('pointerdown', onUserGesture)
    window.addEventListener('keydown', onUserGesture)

    return () => {
      closed = true
      retryTimer.dispose()
      stopAudio()
      pendingAudioRef.current = null
      window.removeEventListener('focus', reconnectSoon)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('pointerdown', onUserGesture)
      window.removeEventListener('keydown', onUserGesture)
      dropSocket()
      void browserMic.stop()
    }
  }, [])

  return { line, status, statusDetail, lastError }
}

function App() {
  const { line, status, statusDetail, lastError } = useChatBridge()
  const frierenStill = useFrierenStill()
  const [pos, setPos] = useState(null)
  const [size, setSize] = useState(null)
  const dragRef = useRef(null)
  const resizeRef = useRef(null)
  const winRef = useRef(null)

  const speakerLabel = line?.who === 'you' ? 'You' : 'Frieren'
  const statusLabel =
    status === 'error' && statusDetail
      ? `Error: ${statusDetail}`
      : STATUS_LABELS[status] || status

  const placed = pos !== null || size !== null

  const ensureGeometry = () => {
    const win = winRef.current
    if (!win) return null
    const rect = win.getBoundingClientRect()
    const nextPos = pos ?? { x: rect.left, y: rect.top }
    const nextSize = size ?? { width: rect.width, height: rect.height }
    if (!pos) setPos(nextPos)
    if (!size) setSize(nextSize)
    return { pos: nextPos, size: nextSize }
  }

  const onTitlePointerDown = (e) => {
    if (e.button !== 0) return
    if (e.target.closest('.title-buttons')) return
    const geo = ensureGeometry()
    if (!geo) return

    dragRef.current = {
      pointerId: e.pointerId,
      offsetX: e.clientX - geo.pos.x,
      offsetY: e.clientY - geo.pos.y,
    }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onTitlePointerMove = (e) => {
    const drag = dragRef.current
    if (!drag || e.pointerId !== drag.pointerId) return
    const w = size?.width ?? winRef.current?.offsetWidth ?? MIN_WIN_W
    const h = size?.height ?? winRef.current?.offsetHeight ?? MIN_WIN_H
    setPos(clampPos(e.clientX - drag.offsetX, e.clientY - drag.offsetY, w, h))
  }

  const onTitlePointerUp = (e) => {
    if (dragRef.current?.pointerId === e.pointerId) {
      dragRef.current = null
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* already released */
      }
    }
  }

  const onResizePointerDown = (dir) => (e) => {
    if (e.button !== 0) return
    e.stopPropagation()
    const geo = ensureGeometry()
    if (!geo) return

    resizeRef.current = {
      pointerId: e.pointerId,
      dir,
      startX: e.clientX,
      startY: e.clientY,
      origin: { ...geo.pos, ...geo.size },
    }
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  const onResizePointerMove = (e) => {
    const resize = resizeRef.current
    if (!resize || e.pointerId !== resize.pointerId) return

    const { dir, startX, startY, origin } = resize
    const dx = e.clientX - startX
    const dy = e.clientY - startY

    let left = origin.x
    let top = origin.y
    let width = origin.width
    let height = origin.height

    if (dir.includes('e')) width = origin.width + dx
    if (dir.includes('s')) height = origin.height + dy
    if (dir.includes('w')) {
      width = origin.width - dx
      left = origin.x + dx
    }
    if (dir.includes('n')) {
      height = origin.height - dy
      top = origin.y + dy
    }

    const nextSize = clampSize(width, height)

    // Keep the anchored edge fixed when hitting min size.
    if (dir.includes('w')) {
      left = origin.x + (origin.width - nextSize.width)
    }
    if (dir.includes('n')) {
      top = origin.y + (origin.height - nextSize.height)
    }

    const nextPos = clampPos(left, top, nextSize.width, nextSize.height)
    setSize(nextSize)
    setPos(nextPos)
  }

  const onResizePointerUp = (e) => {
    if (resizeRef.current?.pointerId === e.pointerId) {
      resizeRef.current = null
      try {
        e.currentTarget.releasePointerCapture(e.pointerId)
      } catch {
        /* already released */
      }
    }
  }

  const winStyle = {
    ...(pos ? { left: pos.x, top: pos.y } : null),
    ...(size ? { width: size.width, height: size.height } : null),
  }

  return (
    <div className="desktop">
      <button
        type="button"
        className="desktop-icon"
        title="Recycle Bin"
        aria-label="Recycle Bin"
        tabIndex={-1}
        onClick={(e) => e.preventDefault()}
      >
        <img src={`${BG_DIR}/recycle_bin.webp`} alt="" width="48" height="48" />
        <span>Recycle Bin</span>
      </button>

      <div
        ref={winRef}
        className={`win${placed ? ' is-dragged' : ' is-centered'}`}
        style={winStyle}
        role="application"
        aria-label="Frieren Grimoire"
      >
        <header
          className="title-bar"
          onPointerDown={onTitlePointerDown}
          onPointerMove={onTitlePointerMove}
          onPointerUp={onTitlePointerUp}
          onPointerCancel={onTitlePointerUp}
        >
          <div className="title-left">
            {frierenStill ? (
              <img className="title-icon" src={frierenStill} alt="" width="16" height="16" />
            ) : null}
            <span className="title-text">Frieren - Grimoire</span>
          </div>
          <TitleButtons />
        </header>

        <div className="client">
          <div className="stage" aria-live="polite">
            <FrierenPortrait
              className="vn-art"
              playing={status === 'speaking'}
              alt="Frieren"
            />

            <div className={`vn-textbox ${line ? `vn-${line.who}` : 'vn-waiting'}`}>
              <div className="vn-name">{line ? speakerLabel : 'Grimoire'}</div>
              <p className="vn-line">
                {line?.text || 'Waiting for voice…'}
              </p>
            </div>
          </div>
        </div>

        <footer className="status-bar">
          <span className="status-cell" title={statusDetail || undefined}>
            {statusLabel}
          </span>
          <span className="status-cell status-right" title={lastError || undefined}>
            {lastError ? `Last error: ${lastError}` : 'Voice companion'}
          </span>
        </footer>

        {RESIZE_HANDLES.map((dir) => (
          <div
            key={dir}
            className={`resize-handle resize-${dir}`}
            onPointerDown={onResizePointerDown(dir)}
            onPointerMove={onResizePointerMove}
            onPointerUp={onResizePointerUp}
            onPointerCancel={onResizePointerUp}
          />
        ))}
      </div>

      <Taskbar />
    </div>
  )
}

export default App
