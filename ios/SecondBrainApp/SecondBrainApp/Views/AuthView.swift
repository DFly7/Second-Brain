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
                Task {
                    guard let window = UIApplication.shared.connectedScenes
                        .compactMap({ $0 as? UIWindowScene })
                        .flatMap({ $0.windows })
                        .first(where: { $0.isKeyWindow })
                    else { return }
                    await authService.signIn(from: window)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
        }
        .padding(32)
    }
}
