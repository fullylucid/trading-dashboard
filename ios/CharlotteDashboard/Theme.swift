import SwiftUI

/// Match the web dashboard's terminal-green-on-black aesthetic.
enum Theme {
    static let green = Color(red: 0.0, green: 1.0, blue: 0.255)   // #00ff41
    static let dim = Color(red: 0.0, green: 1.0, blue: 0.255).opacity(0.55)
    static let bg = Color.black
    static let red = Color(red: 1.0, green: 0.333, blue: 0.333)   // #ff5555
}
