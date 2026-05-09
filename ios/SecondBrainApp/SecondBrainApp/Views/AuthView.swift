import SwiftUI
import UIKit

struct AuthView: View {
    @Environment(AuthService.self) private var authService

    var body: some View {
        VStack(spacing: 24) {
            Text("Second Brain")
                .font(.largeTitle.bold())

            if let error = authService.errorMessage {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Button("Sign in") {
                Task { @MainActor in
                    guard let window = UIApplication.preferredPresentationWindow() else { return }
                    await authService.signIn(from: window)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .padding(32)
    }
}
