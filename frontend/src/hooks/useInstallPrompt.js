import { useEffect, useState } from 'react'

// Chrome/Android fire `beforeinstallprompt` once the site qualifies as an
// installable app (manifest + service worker). It can fire before React has
// mounted, so it's captured at module load and shared with the hook.
let deferredPrompt = null
const listeners = new Set()
const notify = () => listeners.forEach((fn) => fn(deferredPrompt))

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault() // suppress the mini-infobar; we show our own button
    deferredPrompt = e
    notify()
  })
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null
    notify()
  })
}

/** Returns `install` (a function) when the browser offers installation, else null. */
export default function useInstallPrompt() {
  const [prompt, setPrompt] = useState(deferredPrompt)

  useEffect(() => {
    listeners.add(setPrompt)
    return () => listeners.delete(setPrompt)
  }, [])

  if (!prompt) return null
  return async () => {
    prompt.prompt()
    await prompt.userChoice.catch(() => null)
    deferredPrompt = null // a prompt can only be used once
    notify()
  }
}
