import Foundation
import Security

struct APIConfig {
    let backendURL: String
    let authentikAuthorizeURL: String
    let authentikTokenURL: String
    let authentikClientId: String
    let authentikRedirectURI: String

    static let shared: APIConfig = {
        func value(_ key: String) -> String {
            Bundle.main.infoDictionary?[key] as? String ?? ""
        }
        return APIConfig(
            backendURL: value("BACKEND_URL"),
            authentikAuthorizeURL: value("AUTHENTIK_AUTHORIZE_URL"),
            authentikTokenURL: value("AUTHENTIK_TOKEN_URL"),
            authentikClientId: value("AUTHENTIK_CLIENT_ID"),
            authentikRedirectURI: value("AUTHENTIK_REDIRECT_URI")
        )
    }()
}

enum Keychain {
    private static let service = "com.darraghflynn.SecondBrainApp"

    static func save(_ value: String, key: String) {
        guard let data = value.data(using: .utf8) else { return }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecValueData as String: data,
        ]
        SecItemDelete(query as CFDictionary)
        SecItemAdd(query as CFDictionary, nil)
    }

    static func load(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
            kSecMatchLimit as String: kSecMatchLimitOne,
            kSecReturnData as String: true,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    static func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: key,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
