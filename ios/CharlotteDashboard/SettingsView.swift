import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var config: AppConfig
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Dashboard server") {
                    TextField("https://trade.shmaptech.com", text: $config.serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                }
                Section(footer: Text("Sign in with Google through Cloudflare Access inside the app the first time — the session persists, so you stay signed in. Pull down to refresh; the app mirrors the web dashboard, so new features appear automatically.")) {
                    LabeledContent("Version", value: "1.0 (shell)")
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .preferredColorScheme(.dark)
        .tint(Theme.green)
    }
}
