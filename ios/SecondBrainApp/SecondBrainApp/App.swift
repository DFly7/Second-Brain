import SwiftUI

@main
struct SecondBrainApp: App {
    @State private var authService: AuthService
    @State private var apiService: APIService

    init() {
        let auth = AuthService(config: .shared)
        let api = APIService(authService: auth)
        _authService = State(initialValue: auth)
        _apiService = State(initialValue: api)
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(authService)
                .environment(apiService)
        }
    }
}
