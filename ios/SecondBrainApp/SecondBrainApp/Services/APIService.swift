import Foundation
import Observation

@Observable
@MainActor
final class APIService {
    private let authService: AuthService

    init(authService: AuthService) {
        self.authService = authService
    }

    // MARK: - Existing

    func health() async throws -> String {
        let url = URL(string: APIConfig.shared.backendURL + "/health")!
        let data: [String: String] = try await performRequest(url: url, method: "GET")
        return data["status"] ?? "unknown"
    }

    // MARK: - Ingest

    func ingestText(text: String, title: String) async throws {
        let url = URL(string: APIConfig.shared.backendURL + "/ingest/text")!
        let body = try JSONEncoder().encode(["text": text, "title": title])
        let _: IngestResponse = try await performRequest(url: url, method: "POST", body: body, contentType: "application/json")
    }

    func ingestFile(data: Data, filename: String, mimeType: String) async throws {
        let url = URL(string: APIConfig.shared.backendURL + "/ingest/file")!
        let boundary = "Boundary-\(UUID().uuidString)"
        let body = multipartBody(data: data, filename: filename, mimeType: mimeType, boundary: boundary)
        let _: IngestResponse = try await performRequest(
            url: url,
            method: "POST",
            body: body,
            contentType: "multipart/form-data; boundary=\(boundary)"
        )
    }

    // MARK: - Chat

    func sendMessage(text: String, sessionId: String?) async throws -> (answer: String, sessionId: String) {
        let url = URL(string: APIConfig.shared.backendURL + "/chat/message")!
        var payload: [String: String?] = ["message": text, "mode": "query"]
        payload["session_id"] = sessionId
        let body = try JSONEncoder().encode(payload)
        let response: ChatMessageResponse = try await performRequest(url: url, method: "POST", body: body, contentType: "application/json")
        return (response.answer, response.sessionId)
    }

    // MARK: - Private helpers

    private func performRequest<T: Decodable>(
        url: URL,
        method: String,
        body: Data? = nil,
        contentType: String? = nil
    ) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        if let token = authService.accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.httpBody = body
            request.setValue(contentType ?? "application/octet-stream", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw APIError.requestFailed(statusCode: code)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func multipartBody(data: Data, filename: String, mimeType: String, boundary: String) -> Data {
        var body = Data()
        let crlf = "\r\n"
        body.append("--\(boundary)\(crlf)".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\(crlf)".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\(crlf)\(crlf)".data(using: .utf8)!)
        body.append(data)
        body.append("\(crlf)--\(boundary)--\(crlf)".data(using: .utf8)!)
        return body
    }
}

// MARK: - Response types

private struct IngestResponse: Decodable {
    let sourceId: String
    let status: String
    enum CodingKeys: String, CodingKey {
        case sourceId = "source_id"
        case status
    }
}

private struct ChatMessageResponse: Decodable {
    let answer: String
    let sessionId: String
    enum CodingKeys: String, CodingKey {
        case answer
        case sessionId = "session_id"
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
