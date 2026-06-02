import SwiftUI

struct ContentView: View {
    @EnvironmentObject var config: AppConfig
    @State private var isLoading = false
    @State private var canGoBack = false
    @State private var reloadToken = 0
    @State private var goBackToken = 0
    @State private var showSettings = false

    var body: some View {
        ZStack(alignment: .top) {
            Theme.bg.ignoresSafeArea()

            if let url = config.url {
                WebView(url: url, isLoading: $isLoading, canGoBack: $canGoBack,
                        reloadToken: reloadToken, goBackToken: goBackToken)
                    .ignoresSafeArea(edges: .bottom)
            } else {
                VStack(spacing: 12) {
                    Text("No server URL set").foregroundColor(Theme.green)
                    Button("Open Settings") { showSettings = true }.tint(Theme.green)
                }
            }

            // slim top loading bar
            if isLoading {
                ProgressView().tint(Theme.green)
                    .scaleEffect(0.8)
                    .padding(.top, 2)
            }
        }
        // Native controls live in a thin floating cluster so they don't fight the web nav.
        .overlay(alignment: .bottomTrailing) {
            HStack(spacing: 14) {
                if canGoBack {
                    button("chevron.left") { goBackToken += 1 }
                }
                button("arrow.clockwise") { reloadToken += 1 }
                button("gearshape") { showSettings = true }
            }
            .padding(10)
            .background(.black.opacity(0.6), in: Capsule())
            .overlay(Capsule().stroke(Theme.dim, lineWidth: 1))
            .padding(.trailing, 14)
            .padding(.bottom, 24)
        }
        .sheet(isPresented: $showSettings) { SettingsView() }
        .statusBarHidden(false)
    }

    private func button(_ system: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: system)
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(Theme.green)
                .frame(width: 28, height: 28)
        }
    }
}
