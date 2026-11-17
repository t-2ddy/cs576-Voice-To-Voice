import { useEffect, useRef, useState } from 'react'
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

/** Animated GIF while speaking; frozen first frame otherwise. */
function FrierenPortrait({ playing, className, alt }) {
  const stillSrc = useFrierenStill()
  const src = playing ? FRIEREN_ART : stillSrc || FRIEREN_ART

  return (
    <img
      key={playing ? 'playing' : 'paused'}
      className={className}
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
    const retryTimer = createWorkerTimer()

    const stopAudio = () => {
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
    const sendPlaybackDone = () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'playback_done' }))
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
    }

    const playMp3Base64 = (b64) => {
      stopAudio()
      pendingAudioRef.current = null
      try {
        const binary = atob(b64)
        const bytes = new Uint8Array(binary.length)
        for (let i = 0; i < binary.length; i += 1) {
          bytes[i] = binary.charCodeAt(i)
        }
        const blob = new Blob([bytes], { type: 'audio/mpeg' })
        const url = URL.createObjectURL(blob)
        objectUrlRef.current = url
        const audio = new Audio(url)
        audioRef.current = audio
        setStatus('speaking')
        audio.onended = () => {
          stopAudio()
          pendingAudioRef.current = null
          setStatus((s) => (s === 'speaking' ? 'ready' : s))
          sendPlaybackDone()
        }
        audio.onerror = () => {
          stopAudio()
          pendingAudioRef.current = null
          fail('Audio playback failed')
          sendPlaybackDone()
        }
        void audio.play().catch((err) => {
          const blocked =
            err?.name === 'NotAllowedError' ||
            /not allowed|user.*denied|interact/i.test(err?.message || '')
          if (blocked) {
            // Keep the clip; next user gesture will replay it.
            pendingAudioRef.current = b64
            setStatus('error')
            setStatusDetail('Click the window to enable audio')
            setLastError('Click the window to enable audio')
            return
          }
          stopAudio()
          fail(err?.message || 'Audio play blocked')
          sendPlaybackDone()
        })
      } catch (err) {
        stopAudio()
        fail(err?.message || 'Invalid audio payload')
        sendPlaybackDone()
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
        let data
        try {
          data = JSON.parse(event.data)
        } catch {
          return
        }
        if (data.type === 'chat' && data.text) {
          if (data.who === 'you') setLastError('')
          setLine({ who: data.who === 'you' ? 'you' : 'frieren', text: data.text })
        } else if (data.type === 'audio' && data.data) {
          playMp3Base64(data.data)
        } else if (data.type === 'status' && data.value) {
          // Don't let a quick server "ready" clobber local speaking while audio plays.
          if (data.value === 'ready' && audioRef.current && !audioRef.current.paused) {
            return
          }
          setStatus(data.value)
          setStatusDetail(data.detail || '')
          if (data.value === 'error') setLastError(data.detail || 'Unknown error')
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
      const pending = pendingAudioRef.current
      if (pending) {
        pendingAudioRef.current = null
        playMp3Base64(pending)
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
