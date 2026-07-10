import { useEffect, useRef, useState } from 'react'
import './App.css'

const TASKBAR_ICONS = [
  { src: '/icon_home.png', label: 'Start' },
  { src: '/icon_internet_explorer.png', label: 'Internet Explorer' },
  { src: '/icon_file_explorer.png', label: 'File Explorer' },
  { src: '/shiori_still.jpg', label: 'Shiori - Archive' }
]

const TASKBAR_HEIGHT = 40
const MIN_WIN_W = 320
const MIN_WIN_H = 280

const RESIZE_HANDLES = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

const STATUS_LABELS = {
  listening: 'Listening...',
  thinking: 'Thinking...',
  speaking: 'Speaking...',
  ready: 'Ready',
  error: 'Error',
  offline: 'Offline',
  connecting: 'Connecting...',
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

function Taskbar() {
  return (
    <nav className="taskbar" aria-label="Windows taskbar">
      <div className="taskbar-icons">
        {TASKBAR_ICONS.map((icon) => (
          <button
            key={icon.src}
            type="button"
            className="taskbar-icon"
            title={icon.label}
            aria-label={icon.label}
            tabIndex={-1}
            onClick={(e) => e.preventDefault()}
          >
            <img src={icon.src} alt="" width="32" height="32" />
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

function useChatBridge() {
  const [line, setLine] = useState(null)
  const [status, setStatus] = useState('connecting')
  const [statusDetail, setStatusDetail] = useState('')
  const retryRef = useRef(1000)
  const audioRef = useRef(null)
  const objectUrlRef = useRef(null)

  useEffect(() => {
    let ws
    let closed = false
    let timer

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

    const playMp3Base64 = (b64) => {
      stopAudio()
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
          setStatus((s) => (s === 'speaking' ? 'ready' : s))
        }
        audio.onerror = () => {
          stopAudio()
          setStatus('error')
          setStatusDetail('Audio playback failed')
        }
        void audio.play().catch((err) => {
          stopAudio()
          setStatus('error')
          setStatusDetail(err?.message || 'Audio play blocked')
        })
      } catch (err) {
        stopAudio()
        setStatus('error')
        setStatusDetail(err?.message || 'Invalid audio payload')
      }
    }

    const connect = () => {
      if (closed) return
      setStatus((s) =>
        s === 'ready' || s === 'listening' || s === 'thinking' || s === 'speaking'
          ? s
          : 'connecting',
      )
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${window.location.host}/ws`)

      ws.onopen = () => {
        retryRef.current = 1000
        setStatus('ready')
        setStatusDetail('')
      }

      ws.onmessage = (event) => {
        let data
        try {
          data = JSON.parse(event.data)
        } catch {
          return
        }
        if (data.type === 'chat' && data.text) {
          setLine({ who: data.who === 'you' ? 'you' : 'shiori', text: data.text })
        } else if (data.type === 'audio' && data.data) {
          playMp3Base64(data.data)
        } else if (data.type === 'status' && data.value) {
          // Don't let a quick server "ready" clobber local speaking while audio plays.
          if (data.value === 'ready' && audioRef.current && !audioRef.current.paused) {
            return
          }
          setStatus(data.value)
          setStatusDetail(data.detail || '')
        }
      }

      ws.onclose = () => {
        if (closed) return
        setStatus('offline')
        const delay = retryRef.current
        retryRef.current = Math.min(delay * 1.5, 10_000)
        timer = setTimeout(connect, delay)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      closed = true
      clearTimeout(timer)
      stopAudio()
      if (ws) ws.close()
    }
  }, [])

  return { line, status, statusDetail }
}

function App() {
  const { line, status, statusDetail } = useChatBridge()
  const [pos, setPos] = useState(null)
  const [size, setSize] = useState(null)
  const dragRef = useRef(null)
  const resizeRef = useRef(null)
  const winRef = useRef(null)

  const speakerLabel = line?.who === 'you' ? 'You' : 'Shiori'
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
        <img src="/recycle_bin.webp" alt="" width="48" height="48" />
        <span>Recycle Bin</span>
      </button>

      <div
        ref={winRef}
        className={`win${placed ? ' is-dragged' : ' is-centered'}`}
        style={winStyle}
        role="application"
        aria-label="Shiori Archive"
      >
        <header
          className="title-bar"
          onPointerDown={onTitlePointerDown}
          onPointerMove={onTitlePointerMove}
          onPointerUp={onTitlePointerUp}
          onPointerCancel={onTitlePointerUp}
        >
          <div className="title-left">
            <img className="title-icon" src="/shiori.gif" alt="" width="16" height="16" />
            <span className="title-text">Shiori - Archive</span>
          </div>
          <TitleButtons />
        </header>

        <div className="client">
          <div className="stage" aria-live="polite">
            <img
              className="vn-art"
              src="/shiori.gif"
              alt="Shiori Novella"
            />

            <div className={`vn-textbox ${line ? `vn-${line.who}` : 'vn-waiting'}`}>
              <div className="vn-name">{line ? speakerLabel : 'Archive'}</div>
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
          <span className="status-cell status-right">Local companion</span>
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
