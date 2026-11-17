import Foundation

// Transport foundation; no App Store package or device acceptance is claimed.
actor APIClient {
    let baseURL: URL
    private let token: String
    init(baseURL: URL, token: String) { self.baseURL = baseURL; self.token = token }
    func get(_ path: String) async throws -> Data {
        let url = baseURL.appendingPathComponent("v2").appendingPathComponent(path)
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return data
    }
}
