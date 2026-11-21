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
    let workerStatusEndpoint: Bool?
    let crossPageEventSync: Bool?
    let localNotificationCenter: Bool?
}

struct MemoryItem: Codable, Identifiable {
    let id: String
    let text: String
    let revision: Int
    let subject: String?
    let sourceIds: [String]
}

struct CourseItem: Codable, Identifiable {
    let id: String
    let title: String
    let revision: Int
    let stage: String
    let mastered: Bool
    let sourceEligible: Bool?
}

struct ApprovalItem: Codable, Identifiable {
    let id: String
    let revision: Int
    let title: String
    let text: String
    let decision: String?
    let digest: String
    let expiresAt: String
}

struct CardItem: Codable, Identifiable {
    let id: String
    let revision: Int
    let title: String
    let subtype: String
    let remindAt: String?
    let remindedAt: String?
}

struct ModelSummary: Codable {
    let ollamaModel: String?
    let cloudReady: Bool?
    let cloudContext: String?
}

struct SemanticSummary: Codable {
    let enabled: Bool
    let provider: String
    let model: String
    let cloudUsed: Bool
}

struct FairyConfig: Codable {
    var revision: Int
    var dailyMinutes: Int
    var petEnabled: Bool
    var macExecute: Bool
    var macFileWrite: Bool
    var autonomousPaid: Bool
    var macAllowedApps: [String]
    var macAllowedPaths: [String]
    var autonomyEnabled: Bool
    var autonomyDailyMinutes: Int
    var autonomyDailyItems: Int
    var autonomyTopicEnabled: Bool
    var autonomyTopics: [String]
    var petSkin: String
    var petModelUrl: String
    var sourceRefreshEnabled: Bool
    var sourceRefreshIntervalHours: Int
    var sourceRefreshDailyLimit: Int
    var sourceAllowedHosts: [String]

    static let defaultValue = FairyConfig(
        revision: 0,
        dailyMinutes: 45,
        petEnabled: false,
        macExecute: false,
        macFileWrite: false,
        autonomousPaid: false,
        macAllowedApps: [],
        macAllowedPaths: [],
        autonomyEnabled: false,
        autonomyDailyMinutes: 30,
        autonomyDailyItems: 10,
        autonomyTopicEnabled: false,
        autonomyTopics: [],
        petSkin: "builtin",
        petModelUrl: "",
        sourceRefreshEnabled: false,
        sourceRefreshIntervalHours: 24,
        sourceRefreshDailyLimit: 5,
        sourceAllowedHosts: []
    )
}

extension FairyConfig {
    // Tolerate older payloads that predate topic/appearance fields so a
    // read-modify-write PUT never silently resets them to defaults.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        revision = try c.decode(Int.self, forKey: .revision)
        dailyMinutes = try c.decode(Int.self, forKey: .dailyMinutes)
        petEnabled = try c.decode(Bool.self, forKey: .petEnabled)
        macExecute = try c.decode(Bool.self, forKey: .macExecute)
        macFileWrite = try c.decode(Bool.self, forKey: .macFileWrite)
        autonomousPaid = try c.decode(Bool.self, forKey: .autonomousPaid)
        macAllowedApps = try c.decode([String].self, forKey: .macAllowedApps)
        macAllowedPaths = try c.decode([String].self, forKey: .macAllowedPaths)
        autonomyEnabled = try c.decode(Bool.self, forKey: .autonomyEnabled)
        autonomyDailyMinutes = try c.decode(Int.self, forKey: .autonomyDailyMinutes)
        autonomyDailyItems = try c.decode(Int.self, forKey: .autonomyDailyItems)
        autonomyTopicEnabled = try c.decodeIfPresent(Bool.self, forKey: .autonomyTopicEnabled) ?? false
        autonomyTopics = try c.decodeIfPresent([String].self, forKey: .autonomyTopics) ?? []
        petSkin = try c.decodeIfPresent(String.self, forKey: .petSkin) ?? "builtin"
        petModelUrl = try c.decodeIfPresent(String.self, forKey: .petModelUrl) ?? ""
        sourceRefreshEnabled = try c.decode(Bool.self, forKey: .sourceRefreshEnabled)
        sourceRefreshIntervalHours = try c.decode(Int.self, forKey: .sourceRefreshIntervalHours)
        sourceRefreshDailyLimit = try c.decode(Int.self, forKey: .sourceRefreshDailyLimit)
        sourceAllowedHosts = try c.decode([String].self, forKey: .sourceAllowedHosts)
    }
}

struct SkillItem: Codable, Identifiable {
    let id: String
    let revision: Int
    let name: String
    let version: String
    let purpose: String
    let permissions: [String]
    let implementation: String
    let installed: Bool
    let enabled: Bool
}

struct AutonomyBudget: Codable {
    let enabled: Bool
    let dailyMinutes: Int
    let usedMinutes: Int
    let remainingMinutes: Int
    let dailyItems: Int
    let usedItems: Int
    let remainingItems: Int
}

struct AutonomyCandidate: Codable, Identifiable {
    let id: String
    let revision: Int
    let title: String
    let reason: String
    let question: String
    let estimatedMinutes: Int
    let origin: String
    let status: String
}

struct AutonomyGoal: Codable, Identifiable {
    let id: String
    let revision: Int
    let title: String
    let reason: String
    let status: String
    let estimatedMinutes: Int
    let reservedMinutes: Int?
    let spentSeconds: Int?
    let actualMinutes: Int?
    let pauseReason: String?
    let summary: String?
}

struct WorkerStatus: Codable {
    let status: String?
    let alive: Bool?
    let heartbeatAt: String?
    let error: String?
}

actor FairyAPI {
    private let baseURL: URL
    private let token: String
    private let session: URLSession

    init(baseURL: URL, token: String) {
        self.baseURL = baseURL
        self.token = token
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 330
        configuration.timeoutIntervalForResource = 360
        configuration.waitsForConnectivity = true
        self.session = URLSession(configuration: configuration)
    }

    private func request(_ path: String, method: String = "GET", body: Data? = nil) async throws -> Data {
        let components = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        var url = baseURL.appending(path: "v2")
        for component in components[0].split(separator: "/") {
            url.append(path: String(component))
        }
        if components.count > 1, var urlComponents = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            urlComponents.percentEncodedQuery = String(components[1])
            if let resolved = urlComponents.url { url = resolved }
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.httpBody = body
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.setValue(UUID().uuidString, forHTTPHeaderField: "Idempotency-Key")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw URLError(.badServerResponse)
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw NSError(
                domain: "FairyAPI",
                code: http.statusCode,
                userInfo: [NSLocalizedDescriptionKey: detail]
            )
        }
        return data
    }

    private func encode(_ dictionary: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: dictionary)
    }

    private var decoder: JSONDecoder {
        let value = JSONDecoder()
        value.keyDecodingStrategy = .convertFromSnakeCase
        return value
    }

    func capabilities() async throws -> Capabilities {
        return try decoder.decode(Capabilities.self, from: await request("capabilities"))
    }

    func turns() async throws -> [ChatTurn] {
        return try decoder.decode([ChatTurn].self, from: await request("turns"))
    }

    func send(_ text: String) async throws -> ChatTurn {
        let body = try JSONEncoder().encode(["text": text, "routing": "auto"])
        return try decoder.decode(ChatTurn.self, from: await request("turns", method: "POST", body: body))
    }

    func memories() async throws -> [MemoryItem] {
        return try decoder.decode([MemoryItem].self, from: await request("memories"))
    }

    func courses() async throws -> [CourseItem] {
        return try decoder.decode([CourseItem].self, from: await request("learning/courses"))
    }

    func approvals() async throws -> [ApprovalItem] {
        return try decoder.decode([ApprovalItem].self, from: await request("approvals"))
    }

    func cards() async throws -> [CardItem] {
        return try decoder.decode([CardItem].self, from: await request("cards"))
    }

    func modelSummary() async throws -> ModelSummary {
        return try decoder.decode(ModelSummary.self, from: await request("models/config"))
    }

    func semanticSummary() async throws -> SemanticSummary {
        return try decoder.decode(SemanticSummary.self, from: await request("semantic/status"))
    }

    func configs() async throws -> [FairyConfig] {
        try decoder.decode([FairyConfig].self, from: await request("config"))
    }

    func updateConfig(_ config: FairyConfig) async throws -> FairyConfig {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return try decoder.decode(
            FairyConfig.self,
            from: await request("config", method: "PUT", body: encoder.encode(config))
        )
    }

    func correctMemory(id: String, revision: Int, text: String, reason: String) async throws -> MemoryItem {
        let body = try encode(["revision": revision, "text": text, "reason": reason])
        return try decoder.decode(
            MemoryItem.self,
            from: await request("memories/\(id)", method: "PATCH", body: body)
        )
    }

    func forgetMemory(id: String, revision: Int) async throws -> MemoryItem {
        try decoder.decode(
            MemoryItem.self,
            from: await request("memories/\(id)?revision=\(revision)", method: "DELETE")
        )
    }

    func assessCourse(id: String, revision: Int, passed: Bool, evidence: String) async throws -> CourseItem {
        let body = try encode(["revision": revision, "passed": passed, "evidence": evidence])
        return try decoder.decode(
            CourseItem.self,
            from: await request("learning/courses/\(id)/assess", method: "POST", body: body)
        )
    }

    func chooseApproval(_ approval: ApprovalItem, choice: String) async throws -> ApprovalItem {
        let body = try encode([
            "revision": approval.revision,
            "action_digest": approval.digest,
            "choice": choice,
        ])
        return try decoder.decode(
            ApprovalItem.self,
            from: await request("approvals/\(approval.id)/choices", method: "POST", body: body)
        )
    }

    func skills() async throws -> [SkillItem] {
        try decoder.decode([SkillItem].self, from: await request("skills/registry"))
    }

    func installSkill(_ id: String) async throws -> SkillItem {
        try decoder.decode(
            SkillItem.self,
            from: await request("skills/registry/\(id)/install", method: "POST", body: try encode([:]))
        )
    }

    func enableSkill(_ skill: SkillItem) async throws {
        let body = try encode([
            "revision": skill.revision,
            "permissions": skill.permissions,
            "expires_minutes": 60,
        ])
        _ = try await request("skills/registry/\(skill.id)/grant", method: "POST", body: body)
    }

    func disableSkill(_ id: String) async throws {
        _ = try await request("skills/registry/\(id)/disable", method: "POST", body: try encode([:]))
    }

    func invokeSkill(
        _ id: String,
        query: String = "",
        path: String? = nil,
        content: String? = nil
    ) async throws -> String {
        let pathValue: Any = path.map { $0 as Any } ?? NSNull()
        let contentValue: Any = content.map { $0 as Any } ?? NSNull()
        let body = try encode([
            "query": query,
            "path": pathValue,
            "content": contentValue,
        ])
        let data = try await request(
            "skills/registry/\(id)/invoke",
            method: "POST",
            body: body
        )
        let object = try JSONSerialization.jsonObject(with: data)
        let formatted = try JSONSerialization.data(
            withJSONObject: object,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        )
        return String(data: formatted, encoding: .utf8) ?? "{}"
    }

    func autonomyBudget() async throws -> AutonomyBudget {
        try decoder.decode(AutonomyBudget.self, from: await request("autonomy/budget"))
    }

    func autonomyCandidates() async throws -> [AutonomyCandidate] {
        try decoder.decode([AutonomyCandidate].self, from: await request("autonomy/candidates"))
    }

    func autonomyGoals() async throws -> [AutonomyGoal] {
        try decoder.decode([AutonomyGoal].self, from: await request("autonomy/goals"))
    }

    func refreshAutonomy() async throws {
        _ = try await request("autonomy/refresh", method: "POST", body: try encode([:]))
    }

    func acceptCandidate(_ candidate: AutonomyCandidate) async throws {
        _ = try await request(
            "autonomy/candidates/\(candidate.id)/accept",
            method: "POST",
            body: encode(["revision": candidate.revision])
        )
    }

    func dismissCandidate(_ candidate: AutonomyCandidate) async throws {
        _ = try await request(
            "autonomy/candidates/\(candidate.id)/dismiss",
            method: "POST",
            body: encode(["revision": candidate.revision])
        )
    }

    func startGoal(_ goal: AutonomyGoal) async throws {
        _ = try await request(
            "autonomy/goals/\(goal.id)/start",
            method: "POST",
            body: encode(["revision": goal.revision])
        )
    }

    func pauseGoal(_ goal: AutonomyGoal) async throws {
        _ = try await request(
            "autonomy/goals/\(goal.id)/pause",
            method: "POST",
            body: encode(["revision": goal.revision])
        )
    }

    func completeGoal(_ goal: AutonomyGoal, summary: String) async throws {
        _ = try await request(
            "autonomy/goals/\(goal.id)/complete",
            method: "POST",
            body: encode(["revision": goal.revision, "summary": summary])
        )
    }

    func cancelGoal(_ goal: AutonomyGoal) async throws {
        _ = try await request(
            "autonomy/goals/\(goal.id)/cancel",
            method: "POST",
            body: encode(["revision": goal.revision])
        )
    }

    func workerStatus() async throws -> WorkerStatus {
        try decoder.decode(WorkerStatus.self, from: await request("worker/status"))
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
