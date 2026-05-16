import SwiftUI

struct RootView: View {
    @Environment(AuthService.self) private var authService

    var body: some View {
        if authService.isAuthenticated {
            TabView {
                CaptureView()
                    .tabItem {
                        Label("Capture", systemImage: "mic.fill")
                    }

                ChatView()
                    .tabItem {
                        Label("Chat", systemImage: "bubble.left.and.bubble.right.fill")
                    }
            }
        } else {
            AuthView()
        }
    }
}
