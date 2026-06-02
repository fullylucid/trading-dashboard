# Charlotte — iOS app

A native iOS **shell** that wraps the trading dashboard web app. Architecture decision
(2026-06-02): the app **mirrors the web app and evolves alongside it** — the web dashboard
is the single source of truth, so every web feature appears in the app with **zero native
rework**. The native layer only does what the web can't:

- **Cloudflare Access session** — sign in with Google in-app once; the cookie persists.
- **Pull-to-refresh** + native back/refresh/settings controls.
- Roadmap: **push notifications** (Crack-a-Dawn brief, CRITICAL system/signal alerts),
  **Face ID lock**, deep-link tabs.

"Adaptive UI for the phone" is handled on the **web** side (mobile-responsive CSS in the
React app), which also gives a great phone-browser experience with or without the app.

## What's here
```
ios/
  project.yml                      # XcodeGen spec (project as plain text)
  CharlotteDashboard/
    CharlotteDashboardApp.swift    # @main entry
    AppConfig.swift                # server URL (default https://trade.shmaptech.com)
    ContentView.swift              # web shell + floating native controls
    WebView.swift                  # WKWebView (persistent CF Access cookie, pull-to-refresh)
    SettingsView.swift             # change server URL
    Theme.swift                    # terminal-green palette
```

## Build it (needs a Mac with Xcode 15+)

**Option A — XcodeGen (recommended, keeps the project in git as text):**
```bash
brew install xcodegen          # once
cd ios
xcodegen generate              # produces CharlotteDashboard.xcodeproj
open CharlotteDashboard.xcodeproj
```
Then in Xcode: select your Signing Team (Signing & Capabilities), pick your iPhone or a
simulator, and Run (⌘R).

**Option B — manual:** New → Project → iOS App, name it `CharlotteDashboard`, delete the
template `ContentView.swift`, then drag the files from `CharlotteDashboard/` into the project.
Set deployment target to iOS 16. Run.

## First launch
The app loads `https://trade.shmaptech.com`. You'll hit the **Cloudflare Access** login
(Google SSO) inside the app — sign in once and the session persists across launches. Tap the
gear (bottom-right) to change the server URL.

## Why a shell, not a native rebuild
A full SwiftUI rebuild would have to re-implement every dashboard screen and then re-implement
each new feature forever — guaranteed drift. The shell mirrors automatically. As the web app
gets more mobile-responsive, the app's UI improves with it, no app update required.
