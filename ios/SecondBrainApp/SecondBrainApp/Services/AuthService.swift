import AuthenticationServices
import CryptoKit
import Foundation
import Observation
import UIKit

@Observable
@MainActor
final class AuthService: NSObject {
    private(set) var isAuthenticated = false
    private(set) var accessToken: String?
    var errorMessage: String?

    private let config: APIConfig
    private var _presentationAnchor: ASPresentationAnchor?

    init(config: APIConfig) {
        self.config = config
        super.init()
        if let token = Keychain.load(key: "access_token") {
            accessToken = token
            isAuthenticated = true
        }
    }

    func signIn(from anchor: ASPresentationAnchor) async {
        errorMessage = nil
        _presentationAnchor = anchor

        let verifier = generateCodeVerifier()
        let challenge = generateCodeChallenge(from: verifier)

        var components = URLComponents(string: config.authentikAuthorizeURL)!
        components.queryItems = [
            .init(name: "response_type", value: "code"),
            .init(name: "client_id", value: config.authentikClientId),
            .init(name: "redirect_uri", value: config.authentikRedirectURI),
            .init(name: "code_challenge", value: challenge),
            .init(name: "code_challenge_method", value: "S256"),
            .init(name: "scope", value: "openid profile email"),
        ]

        do {
            let callbackURL = try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<URL, Error>) in
                let session = ASWebAuthenticationSession(
                    url: components.url!,
                    callbackURLScheme: "secondbrain"
                ) { url, error in
                    if let error { continuation.resume(throwing: error) }
                    else if let url { continuation.resume(returning: url) }
                    else { continuation.resume(throwing: AuthError.missingCode) }
                }
                session.presentationContextProvider = self
                session.prefersEphemeralWebBrowserSession = false
                session.start()
            }

            guard let code = URLComponents(url: callbackURL, resolvingAgainstBaseURL: false)?
                .queryItems?.first(where: { $0.name == "code" })?.value
            else { throw AuthError.missingCode }

            try await exchangeCode(code, verifier: verifier)
        } catch ASWebAuthenticationSessionError.canceledLogin {
            // User dismissed — not an error
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func signOut() {
        Keychain.delete(key: "access_token")
        accessToken = nil
        isAuthenticated = false
    }

    private func exchangeCode(_ code: String, verifier: String) async throws {
        let url = URL(string: config.authentikTokenURL)!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        let bodyParts = [
            "grant_type=authorization_code",
            "client_id=\(config.authentikClientId.urlEncoded)",
            "code=\(code.urlEncoded)",
            "code_verifier=\(verifier.urlEncoded)",
            "redirect_uri=\(config.authentikRedirectURI.urlEncoded)",
        ]
        request.httpBody = bodyParts.joined(separator: "&").data(using: .utf8)

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
            throw AuthError.tokenExchangeFailed
        }
        let tokens = try JSONDecoder().decode(TokenResponse.self, from: data)
        Keychain.save(tokens.accessToken, key: "access_token")
        accessToken = tokens.accessToken
        isAuthenticated = true
    }

    private func generateCodeVerifier() -> String {
        var bytes = [UInt8](repeating: 0, count: 64)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return Data(bytes).base64URLEncodedString()
    }

    private func generateCodeChallenge(from verifier: String) -> String {
        Data(SHA256.hash(data: Data(verifier.utf8))).base64URLEncodedString()
    }
}

extension AuthService: ASWebAuthenticationPresentationContextProviding {
    nonisolated func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        MainActor.assumeIsolated {
            if let anchor = _presentationAnchor { return anchor }
            guard let window = UIApplication.preferredPresentationWindow() else {
                preconditionFailure("presentationAnchor: no window (use signIn(from:) with a visible window)")
            }
            return window
        }
    }
}

private struct TokenResponse: Decodable {
    let accessToken: String
    enum CodingKeys: String, CodingKey { case accessToken = "access_token" }
}

enum AuthError: LocalizedError {
    case missingCode, tokenExchangeFailed

    var errorDescription: String? {
        switch self {
        case .missingCode: "Missing authorization code in callback"
        case .tokenExchangeFailed: "Token exchange with Authentik failed"
        }
    }
}

private extension Data {
    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

private extension String {
    var urlEncoded: String {
        addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? self
    }
}
