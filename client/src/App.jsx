import { useCallback, useRef, useState } from 'react'
import './App.css'

const MOCK_MESSAGES = [
  { who: 'you', text: 'Hi, my name\'s Theo. Nice to meet you.' },
  {
    who: 'shiori',
    text: 'Oh, dear reader! A name like Theo in my files already… thrilling.',
  },
  { who: 'you', text: 'Do you remember me?' },
  {
    who: 'shiori',
    text: 'Of course I remember — you\'re already bookmarked in my collection.',
  },
]

const TASKBAR_ICONS = [
  { src: '/icon_home.png', label: 'Start' },
  { src: '/icon_internet_explorer.png', label: 'Internet Explorer' },
  { src: '/icon_file_explorer.png', label: 'File Explorer' },
]

const TASKBAR_HEIGHT = 40

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

function App() {
  const [lineIndex, setLineIndex] = useState(0)
  const [pos, setPos] = useState(null)
  const dragRef = useRef(null)
  const winRef = useRef(null)

  const line = MOCK_MESSAGES[lineIndex]
  const speakerLabel = line.who === 'you' ? 'You' : 'Shiori'

  const advance = useCallback(() => {
    setLineIndex((i) => (i + 1) % MOCK_MESSAGES.length)
  }, [])

  const onKeyDown = (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      advance()
    }
  }

  const onTitlePointerDown = (e) => {
    if (e.button !== 0) return
    if (e.target.closest('.title-buttons')) return
    const win = winRef.current
    if (!win) return

    const rect = win.getBoundingClientRect()
    const origin = pos ?? { x: rect.left, y: rect.top }
    dragRef.current = {
      pointerId: e.pointerId,
      offsetX: e.clientX - origin.x,
      offsetY: e.clientY - origin.y,
    }
    e.currentTarget.setPointerCapture(e.pointerId)
    if (!pos) setPos(origin)
  }

  const onTitlePointerMove = (e) => {
    const drag = dragRef.current
    if (!drag || e.pointerId !== drag.pointerId) return
    const win = winRef.current
    if (!win) return

    setPos(
      clampPos(
        e.clientX - drag.offsetX,
        e.clientY - drag.offsetY,
        win.offsetWidth,
        win.offsetHeight,
      ),
    )
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

  const winStyle = pos
    ? { left: pos.x, top: pos.y }
    : undefined

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
        className={`win${pos ? ' is-dragged' : ' is-centered'}`}
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
          <div
            className="stage"
            role="button"
            tabIndex={0}
            onClick={advance}
            onKeyDown={onKeyDown}
            aria-label="Dialogue stage. Press Enter or Space to continue."
          >
            <img
              className="vn-art"
              src="/shiori.gif"
              alt="Shiori Novella"
            />

            <div className={`vn-textbox vn-${line.who}`}>
              <div className="vn-name">{speakerLabel}</div>
              <p className="vn-line">{line.text}</p>
              <span className="vn-hint" aria-hidden="true">
                ▼ Click to continue
              </span>
            </div>
          </div>
        </div>

        <footer className="status-bar">
          <span className="status-cell">Ready</span>
          <span className="status-cell status-right">Local companion</span>
        </footer>
      </div>

      <Taskbar />
    </div>
  )
}

export default App
