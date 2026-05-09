import Foundation
import Observation

@Observable
@MainActor
final class APIService {
    private let authService: AuthService

    init(authService: AuthService) {
        self.authService = authService
    }

    func health() async throws -> String {
        let url = URL(string: APIConfig.shared.backendURL + "/health")!
        var request = URLRequest(url: url)
        request.timeoutInterval = 15
        if let token = authService.accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw APIError.requestFailed(statusCode: code)
        }
        let result = try JSONDecoder().decode([String: String].self, from: data)
        return result["status"] ?? "unknown"
    }
}

enum APIError: LocalizedError {
    case requestFailed(statusCode: Int)

    var errorDescription: String? {
        switch self {
        case .requestFailed(let code): "Request failed (HTTP \(code))"
        }
    }
}
