import Foundation
import Security

struct ChatTurn: Codable, Identifiable {
    let id: String
    let text: String
    let reply: String?
    let status: String
    let error: String?
}

struct Capabilities: Codable {
    let primaryProvider: String?
    let reviewedMemory: Bool?
}

struct MemoryItem: Codable, Identifiable {
    let id: String
    let text: String
    let revision: Int
    let subject: String?
}

struct CourseItem: Codable, Identifiable {
    let id: String
    let title: String
    let stage: String
    let mastered: Bool
}

struct ApprovalItem: Codable, Identifiable {
    let id: String
    let title: String
    let text: String
    let decision: String?
    let expiresAt: String
}

struct ModelSummary: Codable {
    let ollamaModel: String?
    let cloudReady: Bool?
    let cloudContext: String?
}

actor FairyAPI {
    private let baseURL: URL
    private let token: String

    init(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        var request = URLRequest(url: baseURL.appending(path: "v2").appending(path: path))
        request.httpMethod = method
        request.httpBody = body
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return data
    }

    func capabilities() async throws -> Capabilities {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Capabilities.self, from: await request("capabilities"))
    }

    func turns() async throws -> [ChatTurn] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode([ChatTurn].self, from: await request("turns"))
    }

    func send(_ text: String) async throws -> ChatTurn {
        let body = try JSONEncoder().encode(["text": text, "routing": "auto"])
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ChatTurn.self, from: await request("turns", method: "POST", body: body))
    }

    func memories() async throws -> [MemoryItem] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode([MemoryItem].self, from: await request("memories"))
    }

    func courses() async throws -> [CourseItem] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode([CourseItem].self, from: await request("learning/courses"))
    }

    func approvals() async throws -> [ApprovalItem] {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode([ApprovalItem].self, from: await request("approvals"))
    }

    func modelSummary() async throws -> ModelSummary {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(ModelSummary.self, from: await request("models/config"))
    }
}

enum FairyCredential {
    private static let service = "io.fairy.owner"
    private static let account = "local-api-token"

    static func save(_ token: String) throws {
        let data = Data(token.utf8)
        SecItemDelete([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
        ] as CFDictionary)
        let status = SecItemAdd([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecValueData: data,
            kSecAttrAccessible: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,
        ] as CFDictionary, nil)
        guard status == errSecSuccess else { throw URLError(.cannotCreateFile) }
    }

    static func read() -> String? {
        var result: CFTypeRef?
        let status = SecItemCopyMatching([
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: service,
            kSecAttrAccount: account,
            kSecReturnData: true,
            kSecMatchLimit: kSecMatchLimitOne,
        ] as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
