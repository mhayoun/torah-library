import { useEffect, useRef, useState } from 'react'
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize } from 'lucide-react'

let apiLoadPromise = null
function loadYouTubeIframeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT)
  if (apiLoadPromise) return apiLoadPromise
  apiLoadPromise = new Promise((resolve) => {
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

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

// Plays the video via the YouTube IFrame Player API with controls=0, plus a
// transparent overlay blocking all direct interaction with the underlying
// YouTube surface (its own play/pause, related-video screens, logo link,
// etc.) — playback is only controllable through this component's own UI:
// a big center play button (like YouTube's own) to start it with sound,
// play/pause + seek in the header above the video, volume + fullscreen in
// the footer below it. Both bars are hidden while in fullscreen so only the
// video itself shows.
export default function VideoPlayer({ videoId, title, startSeconds }) {
  const containerRef = useRef(null)
  const videoAreaRef = useRef(null)
  const playerRef = useRef(null)
  const seekingRef = useRef(false)

  const [playing, setPlaying] = useState(false)
  const [volume, setVolume] = useState(100)
  const [muted, setMuted] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [fullscreen, setFullscreen] = useState(false)
  const [ready, setReady] = useState(false)
  // Whether playback has actually started at least once. Stays false until
  // the person clicks the big center button (or jumped in via a topic,
  // which is itself a click and starts right away) - browsers only allow
  // unmuted autoplay when it's tied to a direct user gesture like that, so
  // the video loads paused/muted-by-default instead of trying to autoplay.
  const [started, setStarted] = useState(false)

  useEffect(() => {
    function onFullscreenChange() {
      setFullscreen(document.fullscreenElement === videoAreaRef.current)
    }
    document.addEventListener('fullscreenchange', onFullscreenChange)
    return () => document.removeEventListener('fullscreenchange', onFullscreenChange)
  }, [])

  useEffect(() => {
    if (!videoId || !containerRef.current) return
    let destroyed = false

    const playerVars = {
      controls: 0,
      disablekb: 1,
      fs: 0,
      rel: 0,
      modestbranding: 1,
      iv_load_policy: 3,
      playsinline: 1,
      origin: window.location.origin,
    }
    if (startSeconds) playerVars.start = Math.floor(startSeconds)

    loadYouTubeIframeApi().then((YT) => {
      if (destroyed || !containerRef.current) return
      // Held so cleanup can still call destroy() if unmounted before
      // onReady fires; overwritten with the confirmed-functional reference
      // below once it does.
      playerRef.current = new YT.Player(containerRef.current, {
        videoId,
        host: 'https://www.youtube-nocookie.com',
        playerVars,
        events: {
          onReady: (e) => {
            if (destroyed) return
            playerRef.current = e.target
            setDuration(e.target.getDuration())
            setReady(true)
            // Jumping in via a topic chip is itself a click, so that
            // gesture covers unmuted autoplay - start right away with
            // sound on instead of waiting for a second click.
            if (startSeconds) {
              e.target.unMute()
              e.target.setVolume(100)
              e.target.playVideo()
              setStarted(true)
            }
          },
          onStateChange: (e) => {
            setPlaying(e.data === YT.PlayerState.PLAYING)
            setDuration(e.target.getDuration())
          },
        },
      })
    })

    const poll = setInterval(() => {
      if (!playerRef.current || seekingRef.current) return
      try {
        setCurrent(playerRef.current.getCurrentTime())
      } catch {
        // player not fully ready yet - next tick will retry
      }
    }, 500)

    return () => {
      destroyed = true
      clearInterval(poll)
      playerRef.current?.destroy()
      playerRef.current = null
    }
  }, [videoId, startSeconds])

  function handleStart() {
    const p = playerRef.current
    if (!p) return
    p.unMute()
    setMuted(false)
    p.setVolume(volume || 100)
    p.playVideo()
    setStarted(true)
  }

  function togglePlay() {
    const p = playerRef.current
    if (!p) return
    if (playing) p.pauseVideo()
    else p.playVideo()
  }

  function onSeekInput(e) {
    seekingRef.current = true
    setCurrent(Number(e.target.value))
  }

  function commitSeek(e) {
    playerRef.current?.seekTo(Number(e.target.value), true)
    seekingRef.current = false
  }

  function onVolumeInput(e) {
    const v = Number(e.target.value)
    setVolume(v)
    playerRef.current?.setVolume(v)
    if (v > 0 && muted) {
      playerRef.current?.unMute()
      setMuted(false)
    }
  }

  function toggleMute() {
    const p = playerRef.current
    if (!p) return
    if (muted) {
      p.unMute()
      setMuted(false)
    } else {
      p.mute()
      setMuted(true)
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen()
    } else {
      videoAreaRef.current?.requestFullscreen().catch(() => {
        // fullscreen not supported/allowed here - ignore
      })
    }
  }

  return (
    <div
      ref={videoAreaRef}
      style={fullscreen ? { ...styles.root, ...styles.rootFullscreen } : styles.root}
    >
      {/* Hidden in full screen so only the video shows. */}
      {!fullscreen && (
        <div style={styles.bar}>
          <button type="button" onClick={togglePlay} style={styles.iconBtn} aria-label={playing ? 'השהה' : 'נגן'}>
            {playing ? <Pause size={16} /> : <Play size={16} />}
          </button>
          <span style={styles.time}>{formatTime(current)}</span>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={1}
            value={current}
            onChange={onSeekInput}
            onMouseUp={commitSeek}
            onTouchEnd={commitSeek}
            style={styles.range}
            aria-label="מיקום בסרטון"
          />
          <span style={styles.time}>{formatTime(duration)}</span>
        </div>
      )}

      <div style={fullscreen ? { ...styles.videoWrap, ...styles.videoWrapFullscreen } : styles.videoWrap}>
        {videoId ? (
          <>
            <div ref={containerRef} style={styles.iframeLayer} />
            {/* Blocks all direct interaction with the YouTube player underneath */}
            <div style={styles.iframeLayer} />
            {ready && !started && (
              <button
                type="button"
                onClick={handleStart}
                style={styles.centerPlayBtn}
                aria-label="נגן"
              >
                <Play size={34} fill="#fff" />
              </button>
            )}
          </>
        ) : (
          <p style={styles.noVideo}>לא ניתן לטעון את הסרטון</p>
        )}
      </div>

      {/* Hidden in full screen so only the video shows. */}
      {!fullscreen && (
        <div style={styles.bar}>
          <button
            type="button"
            onClick={toggleMute}
            style={styles.iconBtn}
            aria-label={muted ? 'בטל השתקה' : 'השתק'}
          >
            {muted || volume === 0 ? <VolumeX size={16} /> : <Volume2 size={16} />}
          </button>
          <input
            type="range"
            min={0}
            max={100}
            step={1}
            value={muted ? 0 : volume}
            onChange={onVolumeInput}
            style={styles.range}
            aria-label="עוצמת קול"
          />
          <button
            type="button"
            onClick={toggleFullscreen}
            style={styles.iconBtn}
            aria-label={fullscreen ? 'צא ממסך מלא' : 'מסך מלא'}
          >
            {fullscreen ? <Minimize size={16} /> : <Maximize size={16} />}
          </button>
        </div>
      )}
    </div>
  )
}

const styles = {
  root: {
    borderRadius: 10,
    overflow: 'hidden',
    background: '#000',
    border: '1px solid rgba(184,134,11,.15)',
  },
  rootFullscreen: {
    display: 'flex',
    flexDirection: 'column',
    height: '100vh',
    borderRadius: 0,
    border: 'none',
  },
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    background: '#1C1610',
    padding: '6px 10px',
  },
  iconBtn: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    width: 30,
    height: 30,
    borderRadius: '50%',
    border: 'none',
    background: 'transparent',
    color: '#F5F0E8',
    cursor: 'pointer',
  },
  time: {
    flexShrink: 0,
    minWidth: 34,
    textAlign: 'center',
    fontSize: '.7rem',
    fontVariantNumeric: 'tabular-nums',
    color: '#C9BFA8',
    fontFamily: "'Heebo', sans-serif",
  },
  range: {
    flex: 1,
    height: 4,
    accentColor: '#B8860B',
    cursor: 'pointer',
  },
  videoWrap: {
    position: 'relative',
    paddingBottom: '56.25%',
    height: 0,
    background: '#000',
  },
  videoWrapFullscreen: {
    flex: 1,
    paddingBottom: 0,
    height: '100%',
  },
  iframeLayer: {
    position: 'absolute',
    inset: 0,
    width: '100%',
    height: '100%',
  },
  centerPlayBtn: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    zIndex: 2,
    width: 72,
    height: 72,
    borderRadius: '50%',
    border: 'none',
    background: 'rgba(20,16,10,.65)',
    boxShadow: '0 4px 18px rgba(0,0,0,.45)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: '#fff',
    cursor: 'pointer',
  },
  noVideo: {
    position: 'absolute',
    inset: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    textAlign: 'center',
    padding: 24,
    color: '#C9BFA8',
    fontFamily: "'Heebo', sans-serif",
  },
}
