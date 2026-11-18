import SwiftUI
import UserNotifications
import AVFoundation

@MainActor
final class FairyModel: ObservableObject {
    @Published var turns: [ChatTurn] = []
    @Published var memories: [MemoryItem] = []
    @Published var courses: [CourseItem] = []
    @Published var approvals: [ApprovalItem] = []
    @Published var skills: [SkillItem] = []
    @Published var autonomyCandidates: [AutonomyCandidate] = []
    @Published var autonomyGoals: [AutonomyGoal] = []
    @Published var autonomyBudget: AutonomyBudget?
    @Published var workerStatus: WorkerStatus?
    @Published var modelSummary: ModelSummary?
    @Published var semanticSummary: SemanticSummary?
    @Published var skillOutputs: [String: String] = [:]
    @Published var savedAddress = UserDefaults.standard.string(forKey: "fairy.base-url")
        ?? "http://127.0.0.1:8010"
    @Published var status = "未连接"
    @Published var notificationPermission = "未检查"
    @Published var isWorking = false
    @Published var showConnection = false
    @Published var lastError: String?
    private var api: FairyAPI?
    private var pollingTask: Task<Void, Never>?
    private var knownApprovalIDs: Set<String>?
    private let notificationCenter = UNUserNotificationCenter.current()

    func connect(baseURL: String, token: String) async {
        guard let url = URL(string: baseURL),
              let scheme = url.scheme?.lowercased(),
              ["http", "https"].contains(scheme) else {
            status = "地址无效"
            return
        }
        let client = FairyAPI(baseURL: url, token: token)
        do {
            _ = try await client.capabilities()
            api = client
            try FairyCredential.save(token)
            UserDefaults.standard.set(baseURL, forKey: "fairy.base-url")
            savedAddress = baseURL
            status = "已连接本机 Fairy"
            showConnection = false
            await refreshAll()
            startPolling()
        } catch {
            status = "连接失败，请检查地址与令牌"
            lastError = error.localizedDescription
        }
    }

    func restoreConnection() async {
        guard api == nil, let token = FairyCredential.read() else { return }
        await connect(baseURL: savedAddress, token: token)
    }

    private func startPolling() {
        pollingTask?.cancel()
        pollingTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 8_000_000_000)
                guard let self, self.api != nil else { return }
                await self.refreshAll()
            }
        }
    }

    func refreshAll() async {
        guard let api else { return }
        do {
            turns = try await api.turns()
        } catch {
            status = "连接中断"
        }
        if let value = try? await api.memories() { memories = value }
        if let value = try? await api.courses() { courses = value }
        if let value = try? await api.approvals() {
            approvals = value
            await notifyNewApprovals()
        }
        if let value = try? await api.skills() { skills = value }
        if let value = try? await api.autonomyBudget() { autonomyBudget = value }
        if let value = try? await api.autonomyCandidates() {
            autonomyCandidates = value.filter { $0.status == "proposed" }
        }
        if let value = try? await api.autonomyGoals() {
            autonomyGoals = value
        }
        if let value = try? await api.workerStatus() { workerStatus = value }
        if let value = try? await api.modelSummary() { modelSummary = value }
        if let value = try? await api.semanticSummary() { semanticSummary = value }
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
            lastError = error.localizedDescription
        }
    }

    @discardableResult
    private func perform(_ operation: (FairyAPI) async throws -> Void) async -> Bool {
        guard let api else {
            lastError = "尚未连接 Fairy 服务。"
            return false
        }
        isWorking = true
        defer { isWorking = false }
        do {
            try await operation(api)
            await refreshAll()
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    func correctMemory(_ memory: MemoryItem, text: String, reason: String) async -> Bool {
        await perform {
            _ = try await $0.correctMemory(
                id: memory.id,
                revision: memory.revision,
                text: text,
                reason: reason
            )
        }
    }

    func forgetMemory(_ memory: MemoryItem) async -> Bool {
        await perform {
            _ = try await $0.forgetMemory(id: memory.id, revision: memory.revision)
        }
    }

    func assess(_ course: CourseItem, passed: Bool, evidence: String) async -> Bool {
        await perform {
            _ = try await $0.assessCourse(
                id: course.id,
                revision: course.revision,
                passed: passed,
                evidence: evidence
            )
        }
    }

    func chooseApproval(_ approval: ApprovalItem, choice: String) async {
        await perform {
            _ = try await $0.chooseApproval(approval, choice: choice)
        }
    }

    func installSkill(_ skill: SkillItem) async {
        await perform {
            _ = try await $0.installSkill(skill.id)
        }
    }

    func enableSkill(_ skill: SkillItem) async {
        await perform {
            try await $0.enableSkill(skill)
        }
    }

    func disableSkill(_ skill: SkillItem) async {
        await perform {
            try await $0.disableSkill(skill.id)
        }
    }

    func invokeSkill(_ skill: SkillItem, query: String) async {
        guard let api else {
            lastError = "尚未连接 Fairy 服务。"
            return
        }
        isWorking = true
        defer { isWorking = false }
        do {
            skillOutputs[skill.id] = try await api.invokeSkill(skill.id, query: query)
        } catch {
            lastError = error.localizedDescription
        }
    }

    func refreshAutonomy() async {
        await perform {
            try await $0.refreshAutonomy()
        }
    }

    func acceptCandidate(_ candidate: AutonomyCandidate) async {
        await perform {
            try await $0.acceptCandidate(candidate)
        }
    }

    func dismissCandidate(_ candidate: AutonomyCandidate) async {
        await perform {
            try await $0.dismissCandidate(candidate)
        }
    }

    func startGoal(_ goal: AutonomyGoal) async {
        await perform { try await $0.startGoal(goal) }
    }

    func pauseGoal(_ goal: AutonomyGoal) async {
        await perform { try await $0.pauseGoal(goal) }
    }

    func completeGoal(_ goal: AutonomyGoal, summary: String) async {
        await perform { try await $0.completeGoal(goal, summary: summary) }
    }

    func cancelGoal(_ goal: AutonomyGoal) async {
        await perform { try await $0.cancelGoal(goal) }
    }

    func requestNotificationPermission() async {
        do {
            let granted = try await notificationCenter.requestAuthorization(
                options: [.alert, .badge, .sound]
            )
            notificationPermission = granted ? "已授权" : "已拒绝"
            if granted {
                knownApprovalIDs = []
                await notifyNewApprovals()
            }
        } catch {
            notificationPermission = "授权失败"
            lastError = error.localizedDescription
        }
    }

    func refreshNotificationSettings() async {
        let settings = await notificationCenter.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional:
            notificationPermission = "已授权"
        #if os(iOS)
        case .ephemeral:
            notificationPermission = "已授权"
        #endif
        case .denied:
            notificationPermission = "已拒绝"
        case .notDetermined:
            notificationPermission = "未授权"
        @unknown default:
            notificationPermission = "未知"
        }
    }

    private func notifyNewApprovals() async {
        let current = Set(approvals.map(\.id))
        guard let previous = knownApprovalIDs else {
            knownApprovalIDs = current
            return
        }
        let newIDs = current.subtracting(previous)
        knownApprovalIDs = current
        guard !newIDs.isEmpty else { return }
        let settings = await notificationCenter.notificationSettings()
        guard [.authorized, .provisional].contains(settings.authorizationStatus) else {
            return
        }
        for approval in approvals where newIDs.contains(approval.id) {
            let content = UNMutableNotificationContent()
            content.title = "Fairy 有待确认操作"
            content.body = approval.title
            content.sound = .default
            content.userInfo = ["route": "approvals", "id": approval.id]
            let request = UNNotificationRequest(
                identifier: "approval-\(approval.id)-\(approval.revision)",
                content: content,
                trigger: nil
            )
            try? await notificationCenter.add(request)
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
        .tint(Color(red: 0.14, green: 0.37, blue: 0.47))
        .task {
            await model.restoreConnection()
            await model.refreshNotificationSettings()
        }
        .sheet(isPresented: $model.showConnection) {
            ConnectionView()
                .presentationDetents([.medium, .large])
                .presentationDragIndicator(.visible)
        }
        .alert(
            "操作未完成",
            isPresented: Binding(
                get: { model.lastError != nil },
                set: { if !$0 { model.lastError = nil } }
            )
        ) {
            Button("好", role: .cancel) {
                model.lastError = nil
            }
        } message: {
            Text(model.lastError ?? "")
        }
    }

    @ViewBuilder
    private var macDetail: some View {
        switch macSection ?? .conversation {
        case .conversation: ConversationView()
        case .memory: MemoryView()
        case .learning: LearningView()
        case .tasks: TasksView()
        case .autonomy: AutonomyView()
        case .skills: SkillsView()
        case .settings: SettingsView()
        }
    }
}

enum MacSection: String, CaseIterable, Identifiable {
    case conversation, memory, learning, tasks, autonomy, skills, settings

    var id: String { rawValue }

    var title: String {
        switch self {
        case .conversation: "对话"
        case .memory: "记忆"
        case .learning: "学习"
        case .tasks: "待确认"
        case .autonomy: "自主"
        case .skills: "技能"
        case .settings: "设置"
        }
    }

    var symbol: String {
        switch self {
        case .conversation: "bubble.left.and.bubble.right"
        case .memory: "sparkles"
        case .learning: "book.pages"
        case .tasks: "checklist"
        case .autonomy: "arrow.triangle.branch"
        case .skills: "puzzlepiece.extension"
        case .settings: "gearshape"
        }
    }
}

struct ConversationView: View {
    @EnvironmentObject private var model: FairyModel
    @State private var draft = ""
    @State private var speechSynthesizer = AVSpeechSynthesizer()

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 14) {
                        if model.turns.isEmpty {
                            ContentUnavailableView(
                                "和 Fairy 开始对话",
                                systemImage: "sparkles",
                                description: Text("所有长期记忆写入都会先经过你的审阅。")
                            )
                            .frame(minHeight: 320)
                        }
                        ForEach(model.turns) { turn in
                            VStack(alignment: .leading, spacing: 12) {
                                Text(turn.text)
                                    .font(.callout)
                                    .foregroundStyle(.secondary)
                                    .frame(maxWidth: .infinity, alignment: .trailing)
                                Text(turn.reply ?? turn.error ?? "正在处理…")
                                    .padding(14)
                                    .background(
                                        .regularMaterial,
                                        in: RoundedRectangle(cornerRadius: 18, style: .continuous)
                                    )
                                    .frame(maxWidth: .infinity, alignment: .leading)
                            }
                            .id(turn.id)
                        }
                    }
                    .padding()
                }
                .onChange(of: model.turns.count) { _, _ in
                    if let id = model.turns.last?.id {
                        withAnimation(.snappy) { proxy.scrollTo(id, anchor: .bottom) }
                    }
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
                    Button {
                        guard let reply = model.turns.last(where: { $0.reply != nil })?.reply else {
                            return
                        }
                        speechSynthesizer.stopSpeaking(at: .immediate)
                        let utterance = AVSpeechUtterance(string: reply)
                        utterance.voice = AVSpeechSynthesisVoice(language: "zh-CN")
                        speechSynthesizer.speak(utterance)
                    } label: {
                        Image(systemName: "speaker.wave.2")
                    }
                    .help("朗读最新回答")
                    .accessibilityLabel("朗读最新回答")
                    .disabled(!model.turns.contains(where: { $0.reply != nil }))
                }
                ToolbarItem(placement: .primaryAction) {
                    Button { model.showConnection = true } label: {
                        Image(systemName: "link")
                    }
                    .help("连接设置")
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
                        .textContentType(.URL)
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
                if address.isEmpty { address = model.savedAddress }
            }
        }
    }
}

struct MemoryView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.memories) { memory in
                NavigationLink {
                    MemoryDetailView(memory: memory)
                } label: {
                    VStack(alignment: .leading, spacing: 7) {
                        Text(memory.text).font(.body)
                        Text("版本 \(memory.revision) · \(memory.subject ?? "主体待明确")")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 4)
                }
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

struct MemoryDetailView: View {
    @EnvironmentObject private var model: FairyModel
    @Environment(\.dismiss) private var dismiss
    let memory: MemoryItem
    @State private var text: String
    @State private var reason = ""

    init(memory: MemoryItem) {
        self.memory = memory
        _text = State(initialValue: memory.text)
    }

    var body: some View {
        Form {
            Section("当前记忆") {
                TextEditor(text: $text)
                    .frame(minHeight: 130)
                TextField("纠正原因", text: $reason, axis: .vertical)
            }
            Section("来源") {
                ForEach(memory.sourceIds, id: \.self) { id in
                    Text(id).font(.caption.monospaced()).textSelection(.enabled)
                }
            }
            Section {
                Button("保存纠正") {
                    Task {
                        if await model.correctMemory(memory, text: text, reason: reason) {
                            dismiss()
                        }
                    }
                }
                .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || reason.isEmpty)
                Button("遗忘这条记忆", role: .destructive) {
                    Task {
                        if await model.forgetMemory(memory) { dismiss() }
                    }
                }
            }
        }
        .navigationTitle("审阅记忆")
    }
}

struct LearningView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.courses) { course in
                NavigationLink {
                    CourseDetailView(course: course)
                } label: {
                    VStack(alignment: .leading, spacing: 7) {
                        Text(course.title).font(.headline)
                        Text(course.stage).font(.caption).foregroundStyle(.secondary)
                        if course.mastered {
                            Label("已人工确认", systemImage: "checkmark.seal").font(.caption)
                        }
                    }
                    .padding(.vertical, 4)
                }
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

struct CourseDetailView: View {
    @EnvironmentObject private var model: FairyModel
    let course: CourseItem
    @State private var evidence = ""

    var body: some View {
        Form {
            Section("课程") {
                LabeledContent("阶段", value: course.stage)
                LabeledContent("版本", value: String(course.revision))
                if course.sourceEligible == false {
                    Label("来源当前不可用", systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                }
            }
            Section("人工验证") {
                TextField("逐字原文依据", text: $evidence, axis: .vertical)
                    .lineLimit(3...8)
                HStack {
                    Button("记录为通过") {
                        Task { _ = await model.assess(course, passed: true, evidence: evidence) }
                    }
                    Button("仍需练习") {
                        Task { _ = await model.assess(course, passed: false, evidence: evidence) }
                    }
                }
                .disabled(evidence.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .navigationTitle(course.title)
    }
}

struct AutonomyGoalRow: View {
    @EnvironmentObject private var model: FairyModel
    let goal: AutonomyGoal
    @State private var completionSummary = ""
    @State private var confirmCancellation = false

    private var reservedMinutes: Int {
        goal.reservedMinutes ?? goal.estimatedMinutes
    }

    private var canComplete: Bool {
        ["active", "paused"].contains(goal.status)
            && !completionSummary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(goal.title).font(.headline)
            Text(goal.reason).font(.callout).foregroundStyle(.secondary)
            LabeledContent(
                "账本",
                value: "预留 \(reservedMinutes) 分钟 · 已执行 \(goal.actualMinutes ?? 0) 分钟"
            )
            .font(.caption)
            if let pauseReason = goal.pauseReason {
                Text(
                    pauseReason == "budget_exhausted"
                        ? "已达到预留预算并自动暂停。"
                        : "已暂停，预留仍保留。"
                )
                .font(.caption)
                .foregroundStyle(.orange)
            }
            if let summary = goal.summary {
                Text(summary).font(.callout)
            }
            HStack {
                if goal.status == "planned" {
                    Button("开始执行") {
                        Task { await model.startGoal(goal) }
                    }
                    .buttonStyle(.borderedProminent)
                } else if goal.status == "active" {
                    Button("暂停") {
                        Task { await model.pauseGoal(goal) }
                    }
                    .buttonStyle(.bordered)
                } else if goal.status == "paused" {
                    Button("继续执行") {
                        Task { await model.startGoal(goal) }
                    }
                    .buttonStyle(.borderedProminent)
                }
                if ["planned", "active", "paused"].contains(goal.status) {
                    Button("取消目标", role: .destructive) {
                        confirmCancellation = true
                    }
                    .buttonStyle(.bordered)
                }
            }
            .disabled(model.isWorking)
            if ["active", "paused"].contains(goal.status) {
                TextField("完成结果与验证依据", text: $completionSummary, axis: .vertical)
                    .lineLimit(2...6)
                Button("完成并结算") {
                    Task { await model.completeGoal(goal, summary: completionSummary) }
                }
                .buttonStyle(.borderedProminent)
                .disabled(!canComplete || model.isWorking)
            }
        }
        .padding(.vertical, 4)
        .confirmationDialog(
            "取消自主目标？",
            isPresented: $confirmCancellation,
            titleVisibility: .visible
        ) {
            Button("取消目标并释放预留", role: .destructive) {
                Task { await model.cancelGoal(goal) }
            }
            Button("保留目标", role: .cancel) {}
        } message: {
            Text("已执行时间仍会保留在当日账本，剩余预留会释放。")
        }
    }
}

struct TasksView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List {
                Section("待确认") {
                    if model.approvals.filter({ $0.decision == nil }).isEmpty {
                        Text("没有待处理操作").foregroundStyle(.secondary)
                    }
                    ForEach(model.approvals.filter { $0.decision == nil }) { approval in
                        VStack(alignment: .leading, spacing: 8) {
                            Text(approval.title).font(.headline)
                            Text(approval.text).font(.callout).foregroundStyle(.secondary)
                            HStack {
                                Button("批准一次") {
                                    Task { await model.chooseApproval(approval, choice: "allow_once") }
                                }
                                .buttonStyle(.borderedProminent)
                                Button("拒绝", role: .destructive) {
                                    Task { await model.chooseApproval(approval, choice: "reject") }
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }
                Section("执行账本") {
                    if model.autonomyGoals.isEmpty {
                        Text("接受自主候选后可启动受预算约束的目标")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(model.autonomyGoals) { goal in
                        AutonomyGoalRow(goal: goal)
                    }
                }
                Section("自主候选") {
                    if let budget = model.autonomyBudget {
                        Text("今日已用 \(budget.usedMinutes) / \(budget.dailyMinutes) 分钟，候选 \(budget.usedItems) / \(budget.dailyItems)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    if model.autonomyCandidates.isEmpty {
                        Text("没有待处理候选").foregroundStyle(.secondary)
                    }
                    ForEach(model.autonomyCandidates) { candidate in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(candidate.title).font(.headline)
                            Text(candidate.reason).font(.callout).foregroundStyle(.secondary)
                            Text("\(candidate.estimatedMinutes) 分钟 · \(candidate.origin)")
                                .font(.caption)
                            HStack {
                                Button("接受") {
                                    Task { await model.acceptCandidate(candidate) }
                                }
                                .buttonStyle(.borderedProminent)
                                Button("暂不处理") {
                                    Task { await model.dismissCandidate(candidate) }
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    }
                    Button("刷新候选") {
                        Task { await model.refreshAutonomy() }
                    }
                }
                Section("技能") {
                    ForEach(model.skills.prefix(5)) { skill in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(skill.name).font(.headline)
                            Text(skill.purpose).font(.callout).foregroundStyle(.secondary)
                            Text(skill.version + " · " + skill.permissions.joined(separator: "、"))
                                .font(.caption)
                            HStack {
                                if !skill.installed {
                                    Button("安装") { Task { await model.installSkill(skill) } }
                                } else if !skill.enabled {
                                    Button("授权并启用") { Task { await model.enableSkill(skill) } }
                                } else {
                                    Button("停用", role: .destructive) {
                                        Task { await model.disableSkill(skill) }
                                    }
                                }
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
            }
            .navigationTitle("任务")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct AutonomyView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List {
                if let budget = model.autonomyBudget {
                    Section("预算") {
                        LabeledContent("状态", value: budget.enabled ? "已启用" : "已暂停")
                        LabeledContent("分钟", value: "\(budget.usedMinutes) / \(budget.dailyMinutes)")
                        LabeledContent("候选", value: "\(budget.usedItems) / \(budget.dailyItems)")
                    }
                }
                Section("执行账本") {
                    if model.autonomyGoals.isEmpty {
                        Text("接受候选后会在这里生成可启动目标")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(model.autonomyGoals) { goal in
                        AutonomyGoalRow(goal: goal)
                    }
                }
                Section("候选") {
                    ForEach(model.autonomyCandidates) { candidate in
                        VStack(alignment: .leading, spacing: 7) {
                            Text(candidate.title).font(.headline)
                            Text(candidate.reason).font(.callout)
                            HStack {
                                Button("接受") { Task { await model.acceptCandidate(candidate) } }
                                    .buttonStyle(.borderedProminent)
                                Button("暂不处理") { Task { await model.dismissCandidate(candidate) } }
                                    .buttonStyle(.bordered)
                            }
                        }
                    }
                    Button("刷新候选") { Task { await model.refreshAutonomy() } }
                }
            }
            .navigationTitle("自主")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct SkillsView: View {
    @EnvironmentObject private var model: FairyModel

    var body: some View {
        NavigationStack {
            List(model.skills) { skill in
                NavigationLink {
                    SkillDetailView(skill: skill)
                } label: {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(skill.name).font(.headline)
                        Text(skill.purpose).font(.callout).foregroundStyle(.secondary)
                        Text(skill.version + " · " + skill.permissions.joined(separator: "、"))
                            .font(.caption)
                    }
                    .padding(.vertical, 4)
                }
            }
            .navigationTitle("技能")
            .refreshable { await model.refreshAll() }
        }
    }
}

struct SkillDetailView: View {
    @EnvironmentObject private var model: FairyModel
    let skill: SkillItem
    @State private var query = ""

    private var currentSkill: SkillItem {
        model.skills.first(where: { $0.id == skill.id }) ?? skill
    }

    var body: some View {
        Form {
            Section("说明") {
                Text(currentSkill.purpose)
                LabeledContent("版本", value: currentSkill.version)
                LabeledContent("权限", value: currentSkill.permissions.joined(separator: "、"))
            }
            Section("生命周期") {
                if !currentSkill.installed {
                    Button("安装") { Task { await model.installSkill(currentSkill) } }
                } else if !currentSkill.enabled {
                    Button("授权并启用") { Task { await model.enableSkill(currentSkill) } }
                } else {
                    Button("停用并撤销授权", role: .destructive) {
                        Task { await model.disableSkill(currentSkill) }
                    }
                }
            }
            if currentSkill.enabled {
                Section("执行一次") {
                    TextField("Bundle ID、检索词或留空", text: $query)
                    Button("执行") {
                        Task { await model.invokeSkill(currentSkill, query: query) }
                    }
                    if let output = model.skillOutputs[currentSkill.id] {
                        ScrollView {
                            Text(output)
                                .font(.caption.monospaced())
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(maxHeight: 280)
                    }
                }
            }
        }
        .navigationTitle(skill.name)
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
                    LabeledContent(
                        "本地语义嵌入",
                        value: model.semanticSummary?.enabled == true
                            ? model.semanticSummary?.model ?? "已启用"
                            : "未启用"
                    )
                }
                Section("后台") {
                    LabeledContent("Worker", value: model.workerStatus?.status ?? "状态未知")
                    if let heartbeat = model.workerStatus?.heartbeatAt {
                        LabeledContent("最后心跳", value: heartbeat)
                    }
                }
                Section("通知") {
                    LabeledContent("本地通知", value: model.notificationPermission)
                    Button("请求通知权限") {
                        Task { await model.requestNotificationPermission() }
                    }
                    Text("APNs 推送仍需 Apple 签名、推送凭据和真实设备。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Section("隐私") {
                    Text("记忆写入需要人工审阅；云端默认只发送当前问题。")
                }
                Section("设备") {
                    LabeledContent("当前连接", value: model.status)
                    Button("重新加载") { Task { await model.refreshAll() } }
                    Button("连接设置") { model.showConnection = true }
                }
            }
            .navigationTitle("设置")
            .refreshable { await model.refreshAll() }
        }
    }
}
