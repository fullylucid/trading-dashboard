import SwiftUI
import WebKit

/// WKWebView wrapper for the dashboard. Uses the DEFAULT (persistent) data store so the
/// Cloudflare Access session cookie survives app restarts — sign in with Google once,
/// stay signed in. Adds native pull-to-refresh and surfaces load state + back-availability.
struct WebView: UIViewRepresentable {
    let url: URL
    @Binding var isLoading: Bool
    @Binding var canGoBack: Bool
    /// Bump these tokens from the parent to drive actions imperatively.
    let reloadToken: Int
    let goBackToken: Int

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.websiteDataStore = .default()          // persist cookies (CF Access SSO session)
        cfg.allowsInlineMediaPlayback = true
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true

        let web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = true
        web.scrollView.contentInsetAdjustmentBehavior = .always
        web.backgroundColor = .black
        web.isOpaque = false
        web.customUserAgent = (web.value(forKey: "userAgent") as? String).map { $0 + " CharlotteApp/1.0" }

        let refresh = UIRefreshControl()
        refresh.tintColor = UIColor(Theme.green)
        refresh.addTarget(context.coordinator, action: #selector(Coordinator.handleRefresh(_:)), for: .valueChanged)
        web.scrollView.refreshControl = refresh

        context.coordinator.web = web
        web.load(URLRequest(url: url))
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        let c = context.coordinator
        if c.lastReload != reloadToken { c.lastReload = reloadToken; web.reload() }
        if c.lastGoBack != goBackToken { c.lastGoBack = goBackToken; if web.canGoBack { web.goBack() } }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        let parent: WebView
        weak var web: WKWebView?
        var lastReload: Int
        var lastGoBack: Int

        init(_ parent: WebView) {
            self.parent = parent
            self.lastReload = parent.reloadToken
            self.lastGoBack = parent.goBackToken
        }

        @objc func handleRefresh(_ rc: UIRefreshControl) { web?.reload() }

        private func finish(_ w: WKWebView) {
            parent.isLoading = false
            parent.canGoBack = w.canGoBack
            w.scrollView.refreshControl?.endRefreshing()
        }

        func webView(_ w: WKWebView, didStartProvisionalNavigation n: WKNavigation!) { parent.isLoading = true }
        func webView(_ w: WKWebView, didFinish n: WKNavigation!) { finish(w) }
        func webView(_ w: WKWebView, didFail n: WKNavigation!, withError e: Error) { finish(w) }
        func webView(_ w: WKWebView, didFailProvisionalNavigation n: WKNavigation!, withError e: Error) { finish(w) }

        // Open external links (non-dashboard hosts) in Safari instead of trapping them in the shell.
        func webView(_ w: WKWebView, decidePolicyFor nav: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let u = nav.request.url, nav.targetFrame == nil {
                UIApplication.shared.open(u); decisionHandler(.cancel); return
            }
            decisionHandler(.allow)
        }
    }
}
