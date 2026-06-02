import SwiftUI

/// App-wide config. The dashboard server URL is the only thing the user sets; auth happens
/// in-WebView via Cloudflare Access (Google SSO), and the session cookie persists in the
/// WKWebView data store across launches — no token to store on-device.
final class AppConfig: ObservableObject {
    @AppStorage("serverURL") var serverURL: String = "https://trade.shmaptech.com"

    var url: URL? {
        let trimmed = serverURL.trimmingCharacters(in: .whitespacesAndNewlines)
        return URL(string: trimmed.isEmpty ? "https://trade.shmaptech.com" : trimmed)
    }
}
