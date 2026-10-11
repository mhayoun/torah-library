import React, { useEffect, useRef, useState } from 'react'
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize, Captions, CaptionsOff, Languages, Check } from 'lucide-react'

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

// Loading the module alone doesn't display anything for viewers whose
// YouTube preference is captions-off, so the Hebrew track is also selected
// explicitly - retried briefly, since the module loads asynchronously.
function showHebrewCaptions(player) {
  applyCaptions(player, true)
  let tries = 10
  const attempt = () => {
    try {
      const track = player.getOption('captions', 'track')
      if (track?.languageCode && !track.translationLanguage) return
      player.setOption('captions', 'track', { languageCode: 'iw' })
    } catch { /* module not ready yet */ }
    if (--tries > 0) setTimeout(attempt, 400)
  }
  attempt()
}

// Caption language: 'iw' = YouTube's own (auto-generated Hebrew) captions;
// the others are translated from that transcript by our backend
// (GET /api/captions, Gemini) and drawn by this component - YouTube refuses
// its own auto-translated captions (429) inside embedded players.
const CAPTION_LANGUAGES = [
  { code: 'iw', label: 'עברית' },
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'ru', label: 'Русский' },
]
const CC_LANG_STORAGE_KEY = 'player_cc_lang'
function readCcLangPref() {
  try {
    const v = localStorage.getItem(CC_LANG_STORAGE_KEY)
    return CAPTION_LANGUAGES.some(l => l.code === v) ? v : 'iw'
  } catch { return 'iw' }
}

// Translated captions per video+language, kept for the page session so
// reopening a video doesn't refetch.
const translatedCache = new Map()
const sleep = ms => new Promise(res => setTimeout(res, ms))

// The first request for a video+language runs the translation (~20s, up to
// a couple of minutes for long lessons). 202 = someone else's request is
// already translating it, and a 502/504 means the proxy gave up waiting
// while the backend kept going - both just mean "poll until it's cached".
async function fetchTranslatedCaptions(videoId, lang, signal) {
  const key = `${videoId}:${lang}`
  if (translatedCache.has(key)) return translatedCache.get(key)
  for (let attempt = 0; attempt < 40; attempt++) {
    const r = await fetch(`/api/captions/${encodeURIComponent(videoId)}?lang=${lang}`, { signal })
    if (r.status === 202 || r.status === 502 || r.status === 504) {
      await sleep(5000)
      continue
    }
    if (!r.ok) throw new Error({ 404: 'none', 413: 'toolong' }[r.status] || 'unavailable')
    const segments = (await r.json()).segments || []
    translatedCache.set(key, segments)
    return segments
  }
  throw new Error('unavailable')
}

// Lines on screen at time t. Auto-generated segments overlap (a two-line
// roll-up, like YouTube's own display), so up to the last two segments
// that haven't ended yet are shown.
function activeCaptionLines(segments, t) {
  let lo = 0, hi = segments.length - 1, idx = -1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (segments[mid].start <= t) { idx = mid; lo = mid + 1 } else hi = mid - 1
  }
  const lines = []
  for (const i of [idx - 1, idx]) {
    const seg = segments[i]
    if (seg && t < seg.start + seg.duration) lines.push(seg.text)
  }
  return lines
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
// screen), mute/volume/captions/caption-language/fullscreen in the footer.
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
  const [ccLang, setCcLang] = useState(readCcLangPref)
  const ccLangRef = useRef(ccLang)
  const [langMenuOpen, setLangMenuOpen] = useState(false)
  const langMenuRef = useRef(null)
  // Our own translated captions: {status: 'loading'|'ready'|'none'|'toolong'|'unavailable', segments}
  const [translated, setTranslated] = useState(null)
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
            // YouTube's own captions are only wanted for Hebrew; translated
            // ones are drawn by us on top of the video.
            if (e.data === YT.PlayerState.PLAYING) {
              if (ccOnRef.current && ccLangRef.current === 'iw') showHebrewCaptions(e.target)
              else applyCaptions(e.target, false)
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
    }, 250) // 250ms keeps our own drawn captions in step with the speech

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

  function syncYoutubeCaptions() {
    if (!readyRef.current) return
    if (ccOnRef.current && ccLangRef.current === 'iw') showHebrewCaptions(playerRef.current)
    else applyCaptions(playerRef.current, false)
  }

  function toggleCaptions() {
    const next = !ccOn
    setCcOn(next)
    ccOnRef.current = next
    try { localStorage.setItem(CC_STORAGE_KEY, next ? '1' : '0') } catch { /* storage blocked */ }
    syncYoutubeCaptions()
  }

  // Picking a language also turns captions on.
  function selectCaptionLanguage(lang) {
    setLangMenuOpen(false)
    setCcLang(lang)
    ccLangRef.current = lang
    try { localStorage.setItem(CC_LANG_STORAGE_KEY, lang) } catch { /* storage blocked */ }
    if (!ccOnRef.current) toggleCaptions()
    else syncYoutubeCaptions()
  }

  useEffect(() => {
    if (!ccOn || ccLang === 'iw' || !videoId) {
      setTranslated(null)
      return
    }
    const controller = new AbortController()
    setTranslated({ status: 'loading', segments: [] })
    fetchTranslatedCaptions(videoId, ccLang, controller.signal)
      .then(segments => setTranslated({ status: 'ready', segments }))
      .catch(err => {
        if (err.name !== 'AbortError') setTranslated({ status: err.message, segments: [] })
      })
    return () => controller.abort()
  }, [ccOn, ccLang, videoId])

  useEffect(() => {
    if (!langMenuOpen) return
    const onDown = e => { if (!langMenuRef.current?.contains(e.target)) setLangMenuOpen(false) }
    const onKey = e => { if (e.key === 'Escape') setLangMenuOpen(false) }
    document.addEventListener('pointerdown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      window.removeEventListener('keydown', onKey)
    }
  }, [langMenuOpen])

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
  const captionLines = translated?.status === 'ready' ? activeCaptionLines(translated.segments, current) : []
  const captionNote = {
    loading: 'מתרגם כתוביות… (בפעם הראשונה זה עשוי לקחת עד דקה או שתיים)',
    none: 'אין כתוביות לתרגום בשיעור זה',
    toolong: 'תרגום כתוביות זמין לשיעורים של עד כ-20 דקות',
    unavailable: 'התרגום אינו זמין כרגע, נסו שוב מאוחר יותר',
  }[translated?.status]

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
        {(captionLines.length > 0 || captionNote) && (
          <div style={styles.captionArea} aria-live="polite">
            {captionNote ? (
              <span style={{ ...styles.captionLine, ...styles.captionNote }}>{captionNote}</span>
            ) : (
              captionLines.map((line, i) => (
                <span key={i} dir="auto" style={{ ...styles.captionLine, ...(isFull ? styles.captionLineFull : {}) }}>
                  {line}
                </span>
              ))
            )}
          </div>
        )}
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
        <div ref={langMenuRef} style={styles.menuAnchor}>
          <button
            type="button"
            onClick={() => setLangMenuOpen(o => !o)}
            style={{ ...styles.iconBtn, ...(langMenuOpen ? styles.iconBtnActive : {}) }}
            aria-label="שפת כתוביות"
            aria-haspopup="menu"
            aria-expanded={langMenuOpen}
            title="שפת כתוביות"
          >
            <Languages size={18} />
          </button>
          {langMenuOpen && (
            <div style={styles.menu} role="menu">
              <div style={styles.menuHeading}>שפת כתוביות</div>
              {CAPTION_LANGUAGES.map(l => (
                <LangItem
                  key={l.code}
                  label={l.label}
                  selected={ccOn && ccLang === l.code}
                  onClick={() => selectCaptionLanguage(l.code)}
                />
              ))}
              <div style={styles.menuFootnote}>תרגום אוטומטי (AI) מתוך התמלול העברי</div>
            </div>
          )}
        </div>
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

function LangItem({ label, selected, onClick }) {
  return (
    <button
      type="button"
      role="menuitemradio"
      aria-checked={selected}
      onClick={onClick}
      style={{ ...styles.menuItem, ...(selected ? styles.menuItemSelected : {}) }}
    >
      <span style={styles.menuCheck}>{selected && <Check size={14} />}</span>
      {label}
    </button>
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
  iconBtnActive: {
    background: 'rgba(184,134,11,.15)',
  },
  menuAnchor: {
    position: 'relative',
    flexShrink: 0,
  },
  // Opens upward over the video; the player wrapper clips overflow, so the
  // height stays within a small video's area and scrolls.
  menu: {
    position: 'absolute',
    bottom: 'calc(100% + 8px)',
    left: 0,
    zIndex: 5,
    width: 200,
    maxHeight: 220,
    overflowY: 'auto',
    background: '#FFFDF8',
    border: '1px solid rgba(184,134,11,.3)',
    borderRadius: 8,
    boxShadow: '0 6px 20px rgba(0,0,0,.25)',
    padding: '4px 0',
    direction: 'rtl',
  },
  menuHeading: {
    padding: '6px 12px 2px',
    fontSize: '.7rem',
    fontWeight: 600,
    color: '#8B6914',
    fontFamily: "'Heebo', sans-serif",
  },
  menuFootnote: {
    padding: '6px 12px 4px',
    marginTop: 4,
    borderTop: '1px solid rgba(184,134,11,.2)',
    fontSize: '.65rem',
    color: '#8B7D63',
    fontFamily: "'Heebo', sans-serif",
  },
  // Drawn over the click-blocking layer but lets clicks through to it.
  captionArea: {
    position: 'absolute',
    left: '5%',
    right: '5%',
    bottom: '7%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 2,
    pointerEvents: 'none',
  },
  captionLine: {
    maxWidth: '100%',
    padding: '1px 8px',
    background: 'rgba(8,8,8,.75)',
    color: '#fff',
    fontSize: 'clamp(12px, 2.4vw, 18px)',
    lineHeight: 1.35,
    textAlign: 'center',
    borderRadius: 3,
    fontFamily: "'Heebo', 'Arial', sans-serif",
  },
  captionLineFull: {
    fontSize: 'clamp(16px, 2.6vw, 30px)',
  },
  captionNote: {
    fontSize: 'clamp(11px, 2vw, 14px)',
    direction: 'rtl',
  },
  menuItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    width: '100%',
    padding: '6px 12px',
    background: 'transparent',
    border: 'none',
    textAlign: 'right',
    fontSize: '.8rem',
    fontFamily: "'Heebo', sans-serif",
    color: '#1A3A5C',
    cursor: 'pointer',
  },
  menuItemSelected: {
    fontWeight: 600,
    background: 'rgba(184,134,11,.1)',
  },
  menuCheck: {
    display: 'inline-flex',
    width: 14,
    flexShrink: 0,
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
