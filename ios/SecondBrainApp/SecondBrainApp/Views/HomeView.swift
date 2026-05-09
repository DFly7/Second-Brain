import SwiftUI

struct HomeView: View {
    @Environment(AuthService.self) private var authService
    @Environment(APIService.self) private var apiService

    @State private var healthStatus: String?
    @State private var errorMessage: String?
    @State private var isLoading = false

    var body: some View {
        VStack(spacing: 24) {
            Text("Second Brain")
                .font(.largeTitle.bold())

            if let status = healthStatus {
                Label("API status: \(status)", systemImage: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            }

            if let error = errorMessage {
                Text(error)
                    .font(.footnote)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
            }

            Button {
                Task { @MainActor in
                    isLoading = true
                    healthStatus = nil
                    errorMessage = nil
                    do {
                        healthStatus = try await apiService.health()
                    } catch {
                        errorMessage = error.localizedDescription
                    }
                    isLoading = false
                }
            } label: {
                if isLoading {
                    ProgressView().controlSize(.small)
                } else {
                    Text("Test API")
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(isLoading)

            Button("Sign out") {
                authService.signOut()
            }
            .foregroundStyle(.secondary)
        }
        .padding(32)
    }
}
