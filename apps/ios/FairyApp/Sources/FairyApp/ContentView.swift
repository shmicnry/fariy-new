import SwiftUI

@MainActor
final class FairyModel: ObservableObject {
    @Published var turns: [ChatTurn] = []
    @Published var memories: [MemoryItem] = []
    @Published var courses: [CourseItem] = []
    @Published var approvals: [ApprovalItem] = []
    @Published var modelSummary: ModelSummary?
    @Published var savedAddress = UserDefaults.standard.string(forKey: "fairy.base-url")
        ?? "http://127.0.0.1:8000"
    @Published var status = "未连接"
    @Published var isWorking = false
    @Published var showConnection = false
    private var api: FairyAPI?

    func connect(baseURL: String, token: String) async {
        guard let url = URL(string: baseURL) else {
            status = "地址无效"
            return
        }
        api = FairyAPI(baseURL: url, token: token)
        do {
            _ = try await api?.capabilities()
            try FairyCredential.save(token)
            UserDefaults.standard.set(baseURL, forKey: "fairy.base-url")
            savedAddress = baseURL
            status = "已连接本机 Fairy"
            showConnection = false
            await refresh()
            await refreshAll()
        } catch {
            status = "连接失败，请检查地址与令牌"
        }
    }

    func restoreConnection() async {
        guard api == nil, let token = FairyCredential.read() else { return }
        await connect(baseURL: savedAddress, token: token)
    }

    func refresh() async {
        do {
            turns = try await api?.turns() ?? []
        } catch {
            status = "连接中断"
        }
    }

    func send(_ text: String) async {
        guard let api, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        isWorking = true
        defer { isWorking = false }
        do {
            _ = try await api.send(text)
            turns = try await api.turns()
        } catch {
            status = "本轮请求失败"
        }
    }

    func refreshAll() async {
        guard let api else { return }
        do {
            async let memories = api.memories()
            async let courses = api.courses()
            async let approvals = api.approvals()
            async let model = api.modelSummary()
            (self.memories, self.courses, self.approvals, self.modelSummary) = try await (memories, courses, approvals, model)
        } catch {
            status = "部分数据未加载"
        }
    }
}

struct ContentView: View {
    @EnvironmentObject private var model: FairyModel
    @State private var tab = 0
    @State private var macSection: MacSection? = .conversation

    var body: some View {
        Group {
            #if os(macOS)
            NavigationSplitView {
                List(MacSection.allCases, selection: $macSection) { section in
                    Label(section.title, systemImage: section.symbol).tag(section)
                }
                .navigationTitle("Fairy")
                .navigationSplitViewColumnWidth(min: 190, ideal: 220)
            } detail: {
                macDetail
            }
            .navigationSplitViewStyle(.balanced)
            #else
            TabView(selection: $tab) {
                ConversationView().tabItem { Label("对话", systemImage: "bubble.left.and.bubble.right") }.tag(0)
                MemoryView().tabItem { Label("记忆", systemImage: "sparkles") }.tag(1)
                LearningView().tabItem { Label("学习", systemImage: "book.pages") }.tag(2)
                TasksView().tabItem { Label("任务", systemImage: "checklist") }.tag(3)
                SettingsView().tabItem { Label("设置", systemImage: "gearshape") }.tag(4)
            }
            #endif
        }
        .tint(Color(red: 0.16, green: 0.31, blue: 0.44))
        .task { await model.restoreConnection() }
        .sheet(isPresented: $model.showConnection) {
            ConnectionView()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
    }

    @ViewBuilder
    private var macDetail: some View {
        switch macSection ?? .conversation {
        case .conversation:
            ConversationView()
        case .memory:
            MemoryView()
        case .learning:
            LearningView()
        case .tasks:
            TasksView()
        case .settings:
            SettingsView()
        }
    }
}

enum MacSection: String, CaseIterable, Identifiable {
    case conversation, memory, learning, tasks, settings

    var id: String { rawValue }
    var title: String {
        switch self {
        case .conversation: "对话"
        case .memory: "记忆"
        case .learning: "学习"
        case .tasks: "任务"
        case .settings: "设置"
        }
    }
    var symbol: String {
        switch self {
        case .conversation: "bubble.left.and.bubble.right"
        case .memory: "sparkles"
        case .learning: "book.pages"
        case .tasks: "checklist"
        case .settings: "gearshape"
        }
    }
}

struct ConversationView: View {
    @EnvironmentObject private var model: FairyModel
    @State private var draft = ""

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 14) {
                        if model.turns.isEmpty {
                            ContentUnavailableView("和 Fairy 开始对话", systemImage: "sparkles", description: Text("所有记忆写入都会先经过你的审阅。"))
                                .frame(minHeight: 320)
                        }
                        ForEach(model.turns) { turn in
                            VStack(alignment: .leading, spacing: 12) {
                                Text(turn.text).font(.callout).foregroundStyle(.secondary).frame(maxWidth: .infinity, alignment: .trailing)
                                Text(turn.reply ?? turn.error ?? "正在处理…")
                                    .padding(14)
                                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .id(turn.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: model.turns.count) { _, _ in
                    if let id = model.turns.last?.id { withAnimation(.snappy) { proxy.scrollTo(id, anchor: .bottom) } }
                }
            }
            .safeAreaInset(edge: .bottom) {
                HStack(alignment: .bottom, spacing: 10) {
                    TextField("发消息…", text: $draft, axis: .vertical)
                        .padding(12)
                        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 20, style: .continuous))
                    Button {
                        let text = draft
                        draft = ""
                        Task { await model.send(text) }
                    } label: {
                        Image(systemName: model.isWorking ? "ellipsis" : "arrow.up")
                            .font(.headline)
                            .frame(width: 44, height: 44)
                            .background(.tint, in: Circle())
                            .foregroundStyle(.white)
                            .symbolEffect(.pulse, value: model.isWorking)
                    }
                    .disabled(model.isWorking)
                    .keyboardShortcut(.return, modifiers: [.command])
                }
                .padding(.horizontal)
                .padding(.vertical, 8)
                .background(.ultraThinMaterial)
            }
            .navigationTitle("Fairy")
            .sensoryFeedback(.success, trigger: model.turns.count)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button { model.showConnection = true } label: { Image(systemName: "link") }
                }
            }
        }
    }
}

struct ConnectionView: View {
    @EnvironmentObject private var model: FairyModel
    @Environment(\.dismiss) private var dismiss
    @State private var address = ""
    @State private var token = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Fairy 服务") {
                    TextField("服务地址", text: $address)
                    SecureField("所有者令牌", text: $token)
                }
                Section {
                    Button("连接") {
                        Task { await model.connect(baseURL: address, token: token) }
                    }
                    .disabled(token.isEmpty)
                } footer: {
                    Text("令牌保存到系统钥匙串，只用于当前设备。")
                }
            }
            .navigationTitle("连接 Fairy")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
            }
            .onAppear {
                if address.isEmpty {
                    address = model.savedAddress
                }
            }
        }
    }
}

struct PlaceholderView: View {
    let title: String
    let detail: String
    let symbol: String

    var body: some View {
        NavigationStack {
            ContentUnavailableView(title, systemImage: symbol, description: Text(detail))
                .navigationTitle(title)
        }
    }
}

struct MemoryView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.memories) { memory in
                VStack(alignment: .leading, spacing: 7) {
                    Text(memory.text).font(.body)
                    Text("版本 \(memory.revision) · \(memory.subject ?? "主体待明确")")
                        .font(.caption).foregroundStyle(.secondary)
                }.padding(.vertical, 4)
            }
            .overlay {
                if model.memories.isEmpty {
                    ContentUnavailableView("还没有已确认记忆", systemImage: "sparkles")
                }
            }
            .navigationTitle("记忆")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct LearningView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.courses) { course in
                VStack(alignment: .leading, spacing: 7) {
                    Text(course.title).font(.headline)
                    Text(course.stage).font(.caption).foregroundStyle(.secondary)
                    if course.mastered { Label("已人工确认", systemImage: "checkmark.seal").font(.caption) }
                }.padding(.vertical, 4)
            }
            .overlay {
                if model.courses.isEmpty {
                    ContentUnavailableView("还没有学习课程", systemImage: "book.pages")
                }
            }
            .navigationTitle("学习")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct TasksView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.approvals) { approval in
                VStack(alignment: .leading, spacing: 7) {
                    Text(approval.title).font(.headline)
                    Text(approval.text).font(.callout).foregroundStyle(.secondary)
                    Text(approval.decision ?? "等待确认").font(.caption)
                }.padding(.vertical, 4)
            }
            .overlay {
                if model.approvals.isEmpty {
                    ContentUnavailableView("没有待处理任务", systemImage: "checklist")
                }
            }
            .navigationTitle("任务")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct SettingsView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            Form {
                Section("模型") {
                    LabeledContent("本地主模型", value: model.modelSummary?.ollamaModel ?? "未配置")
                    LabeledContent("云副模型", value: model.modelSummary?.cloudReady == true ? "已就绪" : "未启用")
                }
                Section("隐私") {
                    Text("记忆写入需要人工审阅；云端默认只发送当前问题。")
                }
                Section("设备") {
                    LabeledContent("当前连接", value: model.status)
                    Button("重新加载") { Task { await model.refreshAll() } }
                }
            }
            .navigationTitle("设置")
        }
    }
}
