import SwiftUI

// Native iOS shell for the trading dashboard. Architecture: a thin SwiftUI shell wrapping
// the (mobile-responsive) web dashboard, so the app MIRRORS the web app automatically —
// every web feature ships to the phone with zero native rework. The native layer only
// does what the web can't: Cloudflare Access session, pull-to-refresh, push (next), Face ID (next).
@main
struct CharlotteDashboardApp: App {
    @StateObject private var config = AppConfig()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(config)
                .preferredColorScheme(.dark)
                .tint(Theme.green)
        }
    }
}
