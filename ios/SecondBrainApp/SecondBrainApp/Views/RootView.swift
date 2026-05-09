import SwiftUI

struct RootView: View {
    @Environment(AuthService.self) private var authService

    var body: some View {
        if authService.isAuthenticated {
            HomeView()
        } else {
            AuthView()
        }
    }
}
