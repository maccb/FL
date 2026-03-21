# FlickList Scrobbler — Technical Build Outline

> **Created**: Feb 11, 2026 | **Updated**: Feb 11, 2026 | **Status**: 📋 Planning  
> **Classification**: INTERNAL — Do not share implementation details externally  
> **Context**: Packaged inside the FlickList app (flicklist.tv) — not a standalone app

---

## 🎯 OVERVIEW

The scrobbler runs **inside the FlickList app** on the user's device. It operates in the background with user consent, periodically syncing watch history from connected streaming services to the user's FlickList profile. The user is informed the app must remain backgrounded to keep scrobbling active.

**Key principle**: All detection and data capture happens **on the user's device**. Only normalized JSON (title, TMDB ID, timestamp, progress) is transmitted to FlickList servers. No credentials, cookies, tokens, or raw HTML ever leave the device.

---

## 🛠️ TECH STACK

### Backend: Existing flicklist-api (Rust/Axum)

No separate server. Scrobble routes added to the existing Rust binary. Shares the same PostgreSQL DB, same auth middleware, same `media_items` table for TMDB matching.

- New routes: `POST /api/scrobble`, `POST /api/scrobble/batch`, `GET /api/watch-history`
- New migration 024: `watch_history`, `scrobble_sessions`, `service_connections`
- ~500-800 lines of new Rust code
- Splitting to a separate server only considered at 100K+ active scrobbling users

### Mobile App: Capacitor + SvelteKit (Existing Frontend)

The existing flicklist-alpha SvelteKit app becomes the mobile app via Capacitor. Minimal changes to existing code — the app is already mobile-optimized (safe-area insets, touch-action, hover:none queries, dark theme).

**What transfers with zero rewrite:**
- All 20 Svelte components
- 1,626-line typed API client (all endpoints covered)
- Auth flow (JWT + Device Code Auth already built)
- Tailwind CSS design system
- Dark theme, mobile-optimized layout

**What changes for mobile build:**
- SvelteKit switches to `adapter-static` + `ssr: false` (separate build config — web stays SSR)
- SSR `+page.server.ts` load functions become client-side fetches
- API base → always `https://flicklist.tv/api`
- JWT storage → Keychain (iOS) / Keystore (Android) via Capacitor plugin

### Scrobbler: Custom Capacitor Plugins (Native)

The scrobbler is a custom Capacitor plugin written in native code:
- **Android**: Kotlin — `MediaSessionManager`, `WebView`, `WorkManager`, `CookieManager`
- **iOS**: Swift — `WKWebView`, `WKHTTPCookieStore`, `BGTaskScheduler`

The native plugins communicate with the Svelte UI via Capacitor's bridge. Scrobbler settings are rendered in the existing Svelte Settings page.

### Future: KMP Native App (If Needed)

If Capacitor WebView performance is insufficient on low-end streaming devices (Fire TV Stick, etc.), rebuild the UI in Kotlin Multiplatform (Compose) for native performance. **The scrobbler native plugins transfer directly** — they're already Kotlin/Swift. Only the UI shell changes.

### Patterns Ported from CrossWatch (82K line Python sync engine)

| CrossWatch Pattern | What We Take | Ported As |
|-------------------|-------------|-----------|
| `id_map.py` — canonical keys, ID priority chain | ID resolution: `imdb > tmdb > tvdb` | Shared Kotlin/Swift utility (~200 lines) |
| `scrobble.py` — ScrobbleEvent dataclass, Dispatcher | Event model + debounce/filter logic | Shared event model (~150 lines) |
| `_planner.py` — diff source vs dest | Sync diff: device history vs server-known history | Sync planner (~100 lines) |
| `routes.py` — source→sink routing | Per-service config pattern | Service config registry (~80 lines) |
| `scheduling.py` — intervals + jitter | Sync scheduling with jitter | WorkManager/BGTask config (~100 lines) |

**~630 lines of shared logic**, vastly simplified from CrossWatch because we're one-way (device → FlickList) not N-way sync.

---

## 📱 PLATFORM TARGETS

| Platform | Priority | Deployment | Shell |
|----------|----------|------------|-------|
| **Android phones** | 🔴 P0 | Play Store | Capacitor |
| **iOS phones** | 🔴 P0 | App Store | Capacitor |
| **Fire TV** | 🔴 P0 | Amazon Appstore | Capacitor or KMP (if perf needed) |
| **Android TV** | 🔴 P0 | Play Store | Capacitor or KMP (if perf needed) |
| **Apple TV** | 🟡 P1 | App Store (tvOS) | Native Swift |
| **Roku** | 🟡 P1 | Roku Channel Store | BrightScript + phone companion |
| **Desktop (macOS/Windows)** | 🟢 P2 | Capacitor + Electron or Tauri |

---

## 🔧 DETECTION METHODS

### Method A: Session-Based History Sync

The FlickList app contains an embedded browser component. The user authenticates with each streaming service **inside this component**, one time. The app securely stores the resulting session locally (Keychain on iOS, Keystore on Android — hardware-backed, encrypted, never exported).

Periodically (every 4–6 hours, configurable), the app uses the stored session to fetch the user's viewing history from each service's web interface. This happens entirely on-device. The fetched data is parsed into structured records (title, date, type), matched against FlickList's 14M+ TMDB media catalog, deduplicated against previous syncs, and uploaded as clean JSON.

**Supported platforms**: iOS, Android, Fire TV, Android TV, Apple TV, Desktop  
**Data captured**: Historical watch history (backfill + ongoing), completed items  
**Latency**: 4–6 hour polling interval  

### Method B: Real-Time Activity Detection

On platforms that support it, the FlickList app listens for system-level media playback notifications. When any streaming app plays content, the OS broadcasts metadata (title, duration, playback position, play/pause state) for system UI features like lockscreen controls.

The FlickList app captures this metadata passively. No interaction with the streaming app is required — the OS provides the data as a standard platform feature. This enables real-time scrobbling: the moment you press play on Netflix, FlickList knows.

**Supported platforms**: Android, Fire TV, Android TV  
**Not available**: iOS, Apple TV (platform restriction — third-party apps cannot read other apps' media metadata)  
**Data captured**: Currently playing title, duration, progress %, play/pause/stop state  
**Latency**: Real-time (seconds)  
**Requires**: One-time user permission grant in device Settings  

### Method C: Device Network Discovery (Roku, Smart TVs)

For connected devices on the local network, the FlickList phone app can discover and query them using standard device protocols. Some streaming devices expose a local API that reports the currently active app and media state.

**Supported platforms**: Roku (ECP protocol)  
**Data captured**: Active app, media player state  
**Latency**: Near real-time (polling local network)  

### Combined Strategy

| Platform | Method A (History) | Method B (Real-Time) | Method C (Network) |
|----------|-------------------|---------------------|-------------------|
| **Android phone** | ✅ | ✅ | — |
| **Fire TV** | ✅ | ✅ | — |
| **Android TV** | ✅ | ✅ | — |
| **iOS phone** | ✅ | ❌ | — |
| **Apple TV** | ✅ | ❌ | — |
| **Roku** | — | — | ✅ |
| **Desktop** | ✅ | Platform-dependent | — |

---

## 🔋 BATTERY & RESOURCE OPTIMIZATION

### Design Goal: <1% Daily Battery, Invisible in Battery Stats

The scrobbler's total active time per day is ~30-60 seconds. The rest of the time it sleeps completely.

### Method B (Real-Time Detection) — Near-Zero Cost

**Android `NotificationListenerService`:**
- System-managed service — Android keeps it alive automatically with near-zero battery
- Callback-based, NOT polling — code only wakes when a MediaSession event fires
- Same mechanism used by Spotify widgets, sleep timers, and music scrobble apps
- Does NOT appear as a "running service" eating battery in Settings
- No foreground notification needed — runs silently under notification access permission

### Method A (History Sync) — Burst-and-Sleep

**Android `WorkManager`:**
- Periodic job every 4-6 hours with 30-minute flex window
- Constraints: requires network, requires battery not low, requires storage not low
- OS decides exact execution time (batches with other apps, respects Doze mode)
- When triggered: spin up WebView → fetch history (5-15s per service) → parse → POST → kill WebView → done
- With 5 services: ~60 seconds of total active work per sync cycle
- Doze-aware, battery saver-aware — defers sync when user has low power mode on

**iOS `BGTaskScheduler`:**
- `BGAppRefreshTask` — iOS grants ~30 seconds of background time, scheduled at iOS's discretion
- `BGProcessingTask` — for longer work (multiple services), iOS schedules overnight while charging
- Silent push notification from server → triggers background sync (30s budget)
- 15 seconds to fetch history is well within iOS's budget

### What We DON'T Do (Critical)

- ❌ No persistent foreground service with ongoing notification on phones
- ❌ No wakelock holding
- ❌ No periodic alarms that fight Doze mode
- ❌ No WebView kept alive between syncs — spin up, fetch, kill
- ❌ No location, sensors, or network monitoring
- ❌ No polling loops — everything is callback-based or scheduled by the OS

### Streaming Devices — No Constraints

On Fire TV / Android TV / Roku / Apple TV (always plugged in):
- Can run a proper foreground service — battery is irrelevant
- Can poll more aggressively (every 1-2 hours)
- Keep Method B listener running with zero concern
- Full aggressive detection mode

### User-Facing Controls

**Settings → Scrobbling:**

| Setting | Default | Effect |
|---------|---------|--------|
| Sync frequency | Every 6 hours | Longer = less battery. Options: 4h, 6h, 12h, 24h |
| WiFi-only sync | ON | Skips sync on cellular to save data + power |
| Real-time detection | ON (Android only) | Near-zero battery — recommend keeping on |
| Respect battery saver | ON | Defers sync when device is in low power mode |

**User-facing message:**
> *"FlickList syncs your watch history every few hours using minimal battery. Sync only runs when you're connected to WiFi and your battery isn't low. You can adjust frequency or disable syncing anytime in Settings."*

---

## 🎬 STREAMING SERVICE SUPPORT

### Tier 0 — Launch Services (Ship with v1.0)

| Service | Method A (History) | Method B (Real-Time) | Notes |
|---------|-------------------|---------------------|-------|
| **Netflix** | ✅ Well-structured history page | ✅ Broadcasts metadata | Most requested service |
| **Prime Video** | ✅ History accessible | ✅ Broadcasts metadata | Amazon has aggressive anti-bot — distributed device approach mitigates |
| **Hulu** | ✅ Watch history page | ✅ Broadcasts metadata | Standard web history |
| **Disney+** | ✅ Continue watching / history | ✅ Broadcasts metadata | Relatively straightforward |
| **Max (HBO)** | ✅ Continue watching data | ✅ Broadcasts metadata | Formerly HBO Max |

### Tier 1 — Fast Follow (v1.1–v1.2)

| Service | Method A (History) | Method B (Real-Time) | Notes |
|---------|-------------------|---------------------|-------|
| **Apple TV+** | ✅ Web interface available | ✅ (Android) | Apple ecosystem on iOS may need special handling |
| **Peacock** | ✅ Standard web history | ✅ Broadcasts metadata | NBC Universal — low complexity |
| **Paramount+** | ✅ Standard web history | ✅ Broadcasts metadata | Low complexity |
| **Discovery+** | ✅ Web interface | ✅ Broadcasts metadata | May merge with Max |

### Tier 2 — Expansion (v1.3+)

| Service | Method A (History) | Method B (Real-Time) | Notes |
|---------|-------------------|---------------------|-------|
| **Tubi** | ✅ Free service, web history | ✅ Broadcasts metadata | Free ad-supported — large user base |
| **Pluto TV** | ✅ Limited — live TV focus | ✅ Broadcasts metadata | Live/linear TV complicates matching |
| **Roku Channel** | ⚠️ Roku-only web presence | ✅ Via ECP | Tied to Roku devices |
| **Fandango at Home** | ✅ Purchase/rental history | ✅ Broadcasts metadata | Formerly Vudu |
| **Crunchyroll** | ✅ Web history available | ✅ Broadcasts metadata | Anime — strong niche demand |
| **Shudder** | ✅ Web history | ✅ Broadcasts metadata | Horror niche |
| **MUBI** | ✅ Web history | ✅ Broadcasts metadata | Arthouse/indie niche |
| **Plex** | ✅ Has official API | ✅ Broadcasts metadata | Self-hosted media — API-based, easiest integration |
| **YouTube Premium** | ⚠️ Google auth complex | ✅ Broadcasts metadata | Massive user base, Google's anti-scraping is aggressive |

### Per-Service Feasibility (vs Younify)

| Service | Method A (History Sync) | Method B (Real-Time) | Feasibility | Notes |
|---------|------------------------|---------------------|-------------|-------|
| **Netflix** | ✅ `/settings/viewing-history` + Shakti API | ✅ MediaSession on Android | **High** | Best-documented history page |
| **Prime Video** | ✅ `/gp/video/history` | ✅ MediaSession on Android | **High** | Per-device from real IPs mitigates bot detection |
| **Hulu** | ✅ Watch history in account | ✅ MediaSession on Android | **High** | Standard web history |
| **Disney+** | ✅ Continue watching / recently watched | ✅ MediaSession on Android | **High** | Clean structure |
| **Max (HBO)** | ✅ Continue watching data | ✅ MediaSession on Android | **High** | Web interface works |
| **Apple TV+** | ✅ `tv.apple.com` web interface | ✅ MediaSession on Android | **Medium** | iOS `MPNowPlayingInfoCenter` may help |
| **Peacock** | ✅ Standard web watch history | ✅ MediaSession on Android | **High** | Straightforward |
| **Paramount+** | ✅ Standard web watch history | ✅ MediaSession on Android | **High** | Low complexity |
| **Discovery+** | ✅ Web history available | ✅ MediaSession on Android | **Medium** | May merge into Max |
| **Tubi** | ✅ Free service, web history | ✅ MediaSession on Android | **High** | Huge user base |
| **Pluto TV** | ⚠️ Live/linear TV | ✅ MediaSession on Android | **Medium** | Method B saves us for live |
| **Roku Channel** | ⚠️ Limited web presence | ✅ Via Roku ECP API | **Medium** | ECP: `GET /query/media-player` |
| **Fandango at Home** | ✅ Purchase/rental history | ✅ MediaSession on Android | **High** | Formerly Vudu |

### Beyond Younify

| Service | Viability | Why |
|---------|-----------|-----|
| **Crunchyroll** | ✅ High | Anime community, high demand |
| **Shudder** | ✅ High | Horror niche |
| **MUBI** | ✅ High | Arthouse/indie |
| **Plex** | ✅ Trivial | Has public API |
| **YouTube Premium** | ⚠️ Medium | Google's auth is a fortress |
| **Starz** | ✅ High | Standard web interface |
| **AMC+** | ✅ High | Standard web interface |
| **BritBox** | ✅ High | UK/international niche |
| **Curiosity Stream** | ✅ High | Documentary niche |

---

## 🏗️ BUILD PHASES

### Phase 0: Backend Foundation (Weeks 1–3)
*All scrobble routes added to existing flicklist-api.*

- [ ] Scrobble API endpoints — `POST /api/scrobble`, `POST /api/scrobble/batch`, `GET /api/watch-history`
- [ ] Database migration 024: `watch_history`, `scrobble_sessions`, `service_connections`
- [ ] TMDB matching engine (title + year → `media_items` record)
- [ ] Dedup logic (same item from multiple detection methods)
- [ ] Rate limiting and abuse prevention

### Phase 1: FlickList Mobile App — Capacitor Shell (Weeks 4–6)
*Wrap existing flicklist-alpha (SvelteKit) as a native mobile app.*

- [ ] Add Capacitor to flicklist-alpha
- [ ] Separate build config: `adapter-static` + `ssr: false` for mobile
- [ ] Convert SSR load functions to client-side fetches
- [ ] JWT storage → native Keychain/Keystore
- [ ] Push notifications, splash screen, app icons
- [ ] Play Store + App Store submission

### Phase 2: Android Scrobbler Plugin (Weeks 5–8)
*Custom Capacitor plugin in Kotlin.*

- [ ] `ScrobblerPlugin.kt` — Capacitor bridge
- [ ] Method B: `NotificationListenerService` (real-time, near-zero battery)
- [ ] Method A: WebView + CookieManager (session capture + history fetch)
- [ ] WorkManager scheduling (4-6hr, Doze-aware, battery-aware)
- [ ] Keystore credential storage
- [ ] SQLite scrobble queue + retry + dedup
- [ ] Title matcher (local cache + API fallback)

### Phase 3: iOS Scrobbler Plugin (Weeks 7–10)
*Custom Capacitor plugin in Swift.*

- [ ] `ScrobblerPlugin.swift` — Capacitor bridge
- [ ] Method A: WKWebView + WKHTTPCookieStore
- [ ] BGAppRefreshTask + BGProcessingTask scheduling
- [ ] Silent push notification triggers
- [ ] Keychain credential storage
- [ ] SQLite scrobble queue

### Phase 4: Fire TV + Android TV (Weeks 9–11)
*Same Android codebase, TV adaptations.*

- [ ] TV-optimized Svelte layout (D-pad, focus management)
- [ ] Remove battery constraints — aggressive sync (1-2hr)
- [ ] KMP fallback if WebView perf is poor on cheap sticks

### Phase 5: Expansion Services + Roku (Weeks 12–16)

- [ ] Tier 1 + Tier 2 service configs
- [ ] Roku ECP integration
- [ ] Remote config for service config updates
- [ ] Service health monitoring dashboard

### Phase 6: Desktop + Browser Extension (Weeks 16+)

- [ ] Desktop app (Capacitor + Electron or Tauri)
- [ ] Browser extension
- [ ] CSV import for history backfill

---

## 🏛️ APP ARCHITECTURE
