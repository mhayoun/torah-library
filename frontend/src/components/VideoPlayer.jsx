import React, { useEffect, useRef, useState } from 'react'
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize, Captions, CaptionsOff } from 'lucide-react'

// Loads the YouTube IFrame Player API script once and resolves with the
// global YT namespace (shared across every modal opened on the page).
let apiLoadPromise = null
function loadYouTubeIframeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (apiLoadPromise) return apiLoadPromise
  apiLoadPromise = new Promise(resolve => {
    const prevCallback = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      prevCallback?.()
      resolve(window.YT)
    }
    const script = document.createElement('script')
    script.src = 'https://www.youtube.com/iframe_api'
    document.head.appendChild(script)
  })
  return apiLoadPromise
}

// Captions on/off is a per-viewer preference remembered across videos;
// off unless the viewer has turned them on.
const CC_STORAGE_KEY = 'player_cc_on'
function readCcPref() {
  try { return localStorage.getItem(CC_STORAGE_KEY) === '1' } catch { return false }
}

// The IFrame API has no documented captions toggle; loading/unloading the
// captions module is the de-facto way ('cc' is the older module name).
function applyCaptions(player, on) {
  for (const mod of ['captions', 'cc']) {
    try {
      if (on) player.loadModule(mod)
      else player.unloadModule(mod)
    } catch { /* module not available for this video */ }
  }
}

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const total = Math.floor(sec)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

// Plays the video via the YouTube IFrame Player API with controls=0, and a
// transparent overlay blocking all direct interaction with the underlying
// YouTube surface (its logo/title links, related-video end screen, etc.) -
// playback is only controllable through this component's own UI:
// play/pause + position in the header above the video (hidden in full
// screen), mute/volume/captions/fullscreen in the footer below it.
//
// startAt — seconds to start at; changing it while open (a topic or
// transcript chunk clicked in the modal) seeks the running player there
// instead of recreating it.
export default function VideoPlayer({ videoId, title, startAt = null }) {
  const containerRef = useRef(null)
  const wrapperRef = useRef(null)
  const playerRef = useRef(null)
  const readyRef = useRef(false)
  const seekingRef = useRef(false)

  const [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(100)
  const [muted, setMuted] = useState(false)
  const [current, setCurrent] = useState(startAt || 0)
  const [duration, setDuration] = useState(0)
  const [ccOn, setCcOn] = useState(readCcPref)
  // Read inside the YT event handlers, which are bound once per player.
  const ccOnRef = useRef(ccOn)
  // 'native' = Fullscreen API, 'css' = fixed-overlay fallback for browsers
  // without element fullscreen (iPhone Safari), null = normal.
  const [fullscreen, setFullscreen] = useState(null)

  useEffect(() => {
    function onFullscreenChange() {
      const el = document.fullscreenElement || document.webkitFullscreenElement
      setFullscreen(el === wrapperRef.current ? 'native' : null)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    document.addEventListener('webkitfullscreenchange', onFullscreenChange)
    return () => {
      document.removeEventListener('fullscreenchange', onFullscreenChange)
      document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
    }
  }, [])

  useEffect(() => {
    if (fullscreen !== 'css') return
    const onKey = e => { if (e.key === 'Escape') setFullscreen(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [fullscreen])

  useEffect(() => {
    if (!videoId || !containerRef.current) return
    let destroyed = false

    loadYouTubeIframeApi().then(YT => {
      if (destroyed || !containerRef.current) return
      // Held so cleanup can still call destroy() if unmounted before
      // onReady fires; replaced with event.target once it does.
      playerRef.current = new YT.Player(containerRef.current, {
        videoId,
        width: '100%',
        height: '100%',
        host: 'https://www.youtube-nocookie.com',
        playerVars: {
          autoplay: 1,
          controls: 0,
          disablekb: 1,
          fs: 0,
          rel: 0,
          modestbranding: 1,
          iv_load_policy: 3,
          cc_load_policy: 0,
          playsinline: 1,
          hl: 'iw',
          start: startAt ? Math.floor(startAt) : 0,
          origin: window.location.origin,
        },
        events: {
          // The constructor's return value isn't reliably the fully-wired
          // player - event.target here is.
          onReady: e => {
            if (destroyed) return
            playerRef.current = e.target
            readyRef.current = true
            setDuration(e.target.getDuration())
            e.target.setVolume(100)
            e.target.playVideo()
          },
          onStateChange: e => {
            // The captions module only loads once playback starts, so
            // "off" has to be (re)applied here rather than in onReady.
            if (e.data === YT.PlayerState.PLAYING && !ccOnRef.current) {
              applyCaptions(e.target, false)
            }
            setPlaying(e.data === YT.PlayerState.PLAYING)
            setDuration(e.target.getDuration())
          },
        },
      })
    })

    const poll = setInterval(() => {
      if (!readyRef.current || seekingRef.current) return
      try {
        setCurrent(playerRef.current.getCurrentTime())
      } catch {
        // player not fully ready yet - next tick will retry
      }
    }, 500)

    return () => {
      destroyed = true
      clearInterval(poll)
      readyRef.current = false
      try { playerRef.current?.destroy() } catch { /* already gone */ }
      playerRef.current = null
    }
    // startAt is only read for the initial load; later changes are handled
    // by the seek effect below without recreating the player.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId])

  useEffect(() => {
    if (!readyRef.current) return
    const p = playerRef.current
    p.seekTo(startAt || 0, true)
    p.playVideo()
    setCurrent(startAt || 0)
  }, [startAt])

  function togglePlay() {
    const p = playerRef.current
    if (!readyRef.current) return
    if (playing) p.pauseVideo()
    else p.playVideo()
  }

  function onSeekInput(e) {
    seekingRef.current = true
    setCurrent(Number(e.target.value))
  }

  function commitSeek(e) {
    if (readyRef.current) playerRef.current.seekTo(Number(e.currentTarget.value), true)
    seekingRef.current = false
  }

  function onVolumeInput(e) {
    const v = Number(e.target.value)
    setVolume(v)
    if (!readyRef.current) return
    playerRef.current.setVolume(v)
    // Dragging the slider up from a muted state should bring sound back.
    if (muted && v > 0) {
      playerRef.current.unMute()
      setMuted(false)
    }
  }

  function toggleMute() {
    if (!readyRef.current) return
    if (muted) playerRef.current.unMute()
    else playerRef.current.mute()
    setMuted(!muted)
  }

  function toggleCaptions() {
    const next = !ccOn
    setCcOn(next)
    ccOnRef.current = next
    try { localStorage.setItem(CC_STORAGE_KEY, next ? '1' : '0') } catch { /* storage blocked */ }
    if (readyRef.current) applyCaptions(playerRef.current, next)
  }

  function toggleFullscreen() {
    const el = wrapperRef.current
    if (fullscreen === 'native') {
      (document.exitFullscreen || document.webkitExitFullscreen)?.call(document)
      return
    }
    if (fullscreen === 'css') {
      setFullscreen(null)
      return
    }
    const request = el.requestFullscreen || el.webkitRequestFullscreen
    if (request) {
      Promise.resolve(request.call(el)).catch(() => setFullscreen('css'))
    } else {
      setFullscreen('css')
    }
  }

  const isFull = fullscreen !== null
  const isMuted = muted || volume === 0

  return (
    <div
      ref={wrapperRef}
      style={{
        ...styles.wrapper,
        ...(isFull ? styles.wrapperFull : {}),
        ...(fullscreen === 'css' ? styles.wrapperCssFull : {}),
      }}
    >
      {/* Header: play/pause + position. Hidden in full screen so only the
          video (and the footer controls) show. */}
      {!isFull && (
        <div style={{ ...styles.bar, ...styles.headerBar }}>
          <button
            type="button"
            onClick={togglePlay}
            style={styles.iconBtn}
            aria-label={playing ? 'השהה' : 'נגן'}
            title={playing ? 'השהה' : 'נגן'}
          >
            {playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
          </button>
          <span style={styles.time}>{formatTime(current)}</span>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={1}
            value={Math.min(current, duration || 0)}
            onChange={onSeekInput}
            onPointerUp={commitSeek}
            onKeyUp={commitSeek}
            style={styles.range}
            aria-label="מיקום בשיעור"
          />
          <span style={styles.time}>{formatTime(duration)}</span>
        </div>
      )}

      <div style={isFull ? styles.videoAreaFull : styles.videoArea}>
        {/* YT.Player replaces the inner div with its iframe, so it gets its
            own host element and is sized via the width/height options. */}
        <div style={styles.fill}>
          <div ref={containerRef} />
        </div>
        {/* Blocks all direct interaction with the YouTube player underneath;
            a click on the video just toggles play/pause. */}
        <div style={styles.fill} onClick={togglePlay} title={title} />
      </div>

      {/* Footer: mute, volume, fullscreen. */}
      <div style={{ ...styles.bar, ...styles.footerBar }}>
        <button
          type="button"
          onClick={toggleMute}
          style={styles.iconBtn}
          aria-label={isMuted ? 'בטל השתקה' : 'השתק'}
          title={isMuted ? 'בטל השתקה' : 'השתק'}
        >
          {isMuted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={muted ? 0 : volume}
          onChange={onVolumeInput}
          style={{ ...styles.range, ...styles.volumeRange }}
          aria-label="עוצמת קול"
        />
        <div style={{ flex: 1 }} />
        <button
          type="button"
          onClick={toggleCaptions}
          style={styles.iconBtn}
          aria-label={ccOn ? 'הסתר כתוביות' : 'הצג כתוביות'}
          aria-pressed={ccOn}
          title={ccOn ? 'הסתר כתוביות' : 'הצג כתוביות'}
        >
          {ccOn ? <Captions size={18} /> : <CaptionsOff size={18} />}
        </button>
        <button
          type="button"
          onClick={toggleFullscreen}
          style={styles.iconBtn}
          aria-label={isFull ? 'צא ממסך מלא' : 'מסך מלא'}
          title={isFull ? 'צא ממסך מלא' : 'מסך מלא'}
        >
          {isFull ? <Minimize size={18} /> : <Maximize size={18} />}
        </button>
      </div>
    </div>
  )
}

const styles = {
  wrapper: {
    borderRadius: 10,
    overflow: 'hidden',
    marginBottom: 20,
    background: '#000',
    border: '1px solid rgba(184,134,11,.25)',
  },
  wrapperFull: {
    display: 'flex',
    flexDirection: 'column',
    width: '100%',
    height: '100%',
    borderRadius: 0,
    border: 'none',
    margin: 0,
  },
  wrapperCssFull: {
    position: 'fixed',
    inset: 0,
    zIndex: 2000,
    width: '100vw',
    height: '100dvh',
  },
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 10px',
    background: '#F5F0E8',
  },
  headerBar: {
    borderBottom: '1px solid rgba(184,134,11,.2)',
  },
  footerBar: {
    borderTop: '1px solid rgba(184,134,11,.2)',
  },
  iconBtn: {
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 34,
    height: 34,
    borderRadius: '50%',
    background: 'transparent',
    border: 'none',
    color: '#1A3A5C',
    cursor: 'pointer',
  },
  time: {
    flexShrink: 0,
    minWidth: 38,
    textAlign: 'center',
    fontSize: '.75rem',
    fontVariantNumeric: 'tabular-nums',
    fontFamily: "'Heebo', sans-serif",
    color: '#3D3323',
  },
  range: {
    flex: 1,
    minWidth: 0,
    height: 6,
    accentColor: '#B8860B',
    cursor: 'pointer',
  },
  volumeRange: {
    flex: '0 1 140px',
  },
  videoArea: {
    position: 'relative',
    paddingBottom: '56.25%',
    height: 0,
    background: '#000',
  },
  videoAreaFull: {
    position: 'relative',
    flex: 1,
    background: '#000',
  },
  fill: {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
  },
}
