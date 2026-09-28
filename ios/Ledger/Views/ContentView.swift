import SwiftUI

/// Business shows what an owner acts on; Activity shows every API call for developers.
enum TimelineMode: String, CaseIterable {
    case business = "Business", activity = "Activity"
}

/// Two tabs: the live agent, and payments waiting for the owner's decision.
struct RootView: View {
    enum Tab { case ledger, approvals, history }
    @State private var tab = Tab.ledger
    @State private var session = AgentSession.shared

    var body: some View {
        TabView(selection: $tab) {
            ContentView(onReviewApprovals: { tab = .approvals })
                .tabItem { Label("Ledger", systemImage: "waveform") }
                .tag(Tab.ledger)
            ApprovalsView()
                .tabItem { Label("Approvals", systemImage: "checkmark.shield") }
                .badge(session.pendingApprovals.count)
                .tag(Tab.approvals)
            HistoryView()
                .tabItem { Label("History", systemImage: "clock.arrow.circlepath") }
                .tag(Tab.history)
        }
    }
}

struct ContentView: View {
    var onReviewApprovals: () -> Void = {}
    @State private var session = AgentSession.shared
    @State private var voice = VoiceInput()
    @State private var submitAfterVoice = false
    @AppStorage("speakResults") private var speakResults = true
    @AppStorage("timelineMode") private var timelineMode = TimelineMode.business
    @State private var prompt = ""
    @State private var showSettings = false
    @FocusState private var promptFocused: Bool
    @Namespace private var modeNamespace

    private let suggestions = [
        "Brief me. How's the business doing today?",
        "Investigate today's PayPal disputes and handle them.",
        "Fight the chargebacks we can win and tell the team.",
    ]
    private let allServices = ["paypal", "notion", "gmail", "jira", "slack"]

    var body: some View {
        NavigationStack {
            screen
                .ledgerBackground()
                .toolbar(.hidden, for: .navigationBar)
                .sheet(isPresented: $showSettings) { SettingsView() }
                .alert("Voice", isPresented: voiceErrorShown) {
                    Button("OK", role: .cancel) {}
                } message: {
                    Text(voice.errorMessage ?? "")
                }
                .task { await session.connect() }
        }
    }

    /// Main layout + state observers, split out so the compiler can type-check `body` quickly.
    private var screen: some View {
        VStack(spacing: 0) {
            header
            serviceStrip
            modePicker
            approvalBanner
            timeline
                .safeAreaInset(edge: .bottom, spacing: 0) { composer }
        }
        .onChange(of: session.queuedPrompt, initial: true) { _, newValue in handleQueued(newValue) }
        .onChange(of: voice.transcript) { _, text in handleTranscript(text) }
        .onChange(of: voice.isRecording) { _, recording in handleRecording(recording) }
        .onChange(of: session.finalResult) { _, final in handleFinal(final) }
    }

    private var voiceErrorShown: Binding<Bool> {
        Binding(get: { voice.errorMessage != nil },
                set: { if !$0 { voice.errorMessage = nil } })
    }

    private func handleQueued(_ newValue: String?) {
        guard let text = newValue else { return }
        session.queuedPrompt = nil
        prompt = text
        submit()
    }

    private func handleTranscript(_ text: String) {
        if voice.isRecording { prompt = text }
    }

    private func handleRecording(_ recording: Bool) {
        if !recording && submitAfterVoice {
            submitAfterVoice = false
            submit()
        }
    }

    private func handleFinal(_ final: AgentEvent?) {
        if speakResults, let text = final?.detail { Speaker.shared.say(text) }
    }

    // MARK: - Sections

    /// Own header instead of the system bar: serif gold wordmark, live status, settings.
    private var header: some View {
        HStack(alignment: .center, spacing: 10) {
            Text("Ledger")
                .font(Theme.display(36, .bold))
                .foregroundStyle(Theme.pearl)
                .glow(Theme.accent, radius: 14, strength: 0.7)
            Spacer()
            connectionDot
            Button { showSettings = true } label: {
                Image(systemName: "slider.horizontal.3")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Theme.accentLight)
                    .frame(width: 36, height: 36)
                    .background(Theme.raised.opacity(0.85), in: Circle())
                    .overlay(Circle().strokeBorder(Theme.hairline, lineWidth: 0.5))
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal)
        .padding(.top, 6)
        .padding(.bottom, 12)
    }

    private var serviceStrip: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 6) {
                ForEach(allServices, id: \.self) { s in
                    ServiceBadge(service: s, active: session.servicesUsed.contains(s))
                }
                if session.toolCallCount > 0 {
                    Text("\(session.toolCallCount) API calls")
                        .font(Theme.sans(11, .medium, relativeTo: .caption2).monospacedDigit())
                        .foregroundStyle(Theme.accent.opacity(0.8))
                        .padding(.leading, 4)
                }
            }
            .padding(.horizontal)
            .padding(.top, 4)
            .padding(.bottom, 10)
            .animation(.snappy, value: session.servicesUsed)
        }
    }

    @ViewBuilder private var approvalBanner: some View {
        let pending = session.pendingApprovals
        if !pending.isEmpty {
            Button(action: onReviewApprovals) {
                HStack(spacing: 12) {
                    Image(systemName: "hand.raised.fill")
                        .font(Theme.sans(20, .regular, relativeTo: .title3))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(pending.count == 1 ? "1 payment needs your approval" : "\(pending.count) payments need your approval")
                            .font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                        Text(pending.map(\.request.title).joined(separator: " · "))
                            .font(Theme.sans(12, .regular, relativeTo: .caption))
                            .lineLimit(1)
                            .opacity(0.85)
                    }
                    Spacer()
                    Text("Review").font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                    Image(systemName: "chevron.right").font(Theme.sans(12, .bold, relativeTo: .caption))
                }
                .foregroundStyle(Theme.onAccent)
                .padding(14)
                .background(Theme.accentGradient, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                .shadow(color: Theme.accent.opacity(0.35), radius: 14, y: 4)
            }
            .buttonStyle(.plain)
            .padding(.horizontal)
            .padding(.bottom, 8)
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    private var modePicker: some View {
        HStack(spacing: 4) {
            ForEach(TimelineMode.allCases, id: \.self) { mode in
                let selected = timelineMode == mode
                Button {
                    withAnimation(.snappy) { timelineMode = mode }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: mode == .business ? "briefcase.fill" : "chevron.left.forwardslash.chevron.right")
                            .font(Theme.sans(12, .regular, relativeTo: .caption))
                        Text(mode.rawValue)
                        if mode == .activity && hiddenCount > 0 {
                            Text("\(hiddenCount)")
                                .font(Theme.sans(11, .bold, relativeTo: .caption2).monospacedDigit())
                                .padding(.horizontal, 6)
                                .padding(.vertical, 1)
                                .background(Theme.accent.opacity(0.2), in: Capsule())
                        }
                    }
                    .font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                    .foregroundStyle(selected ? Theme.accentDeep : Theme.textDim)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 9)
                    .background {
                        if selected {
                            Capsule().fill(Theme.pearl)
                                .glow(Theme.accent, radius: 10, strength: 0.55)
                                .matchedGeometryEffect(id: "mode", in: modeNamespace)
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(4)
        .background(Theme.raised.opacity(0.85), in: Capsule())
        .overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: 0.5))
        .padding(.horizontal)
        .padding(.bottom, 10)
    }

    /// Events a business owner cares about: the request, evidence, approvals, decisions, the answer.
    private func isBusinessEvent(_ event: AgentEvent) -> Bool {
        switch event.type {
        case .toolCall, .toolResult, .decision: return false
        default: return true
        }
    }

    private var visibleEvents: [AgentEvent] {
        timelineMode == .business ? session.events.filter(isBusinessEvent) : session.events
    }

    private var hiddenCount: Int { session.events.count - session.events.filter(isBusinessEvent).count }

    private var timeline: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    if session.events.isEmpty && !session.isRunning {
                        emptyState
                    }
                    ForEach(visibleEvents) { event in
                        EventRow(event: event)
                            .id(event.id)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }
                    if session.isRunning, let status = session.statusText {
                        HStack(spacing: 10) {
                            ProgressView().tint(Theme.accent)
                            Text(status)
                                .font(Theme.sans(13, .medium, relativeTo: .footnote))
                                .foregroundStyle(Theme.accentLight)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .ledgerCard(radius: 14)
                        .id("status")
                    }
                    if timelineMode == .business && hiddenCount > 0 {
                        Button {
                            timelineMode = .activity
                        } label: {
                            Label("\(hiddenCount) behind-the-scenes steps across \(session.servicesUsed.map(ServiceStyle.name).joined(separator: ", ")). View in Activity",
                                  systemImage: "chevron.left.forwardslash.chevron.right")
                                .font(Theme.sans(12, .medium, relativeTo: .caption))
                                .foregroundStyle(Theme.accent.opacity(0.85))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        .padding(.horizontal, 4)
                        .padding(.top, 4)
                    }
                }
                .padding(.horizontal)
                .padding(.bottom, 12)
                .animation(.snappy, value: session.events)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: session.events.count) {
                let target = session.isRunning ? "status" : (visibleEvents.last?.id ?? "status")
                withAnimation { proxy.scrollTo(target, anchor: .bottom) }
            }
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 18) {
            HeroMiniature()
                .padding(.bottom, 4)
            VStack(alignment: .leading, spacing: 8) {
                Text("Your AI COO")
                    .font(Theme.display(30))
                    .foregroundStyle(Theme.text)
                Text("Ask how the business is doing, or send Ledger to investigate PayPal chargebacks. It gathers evidence from Gmail and Notion, fights the ones you can win, and asks you before any money moves.")
                    .font(Theme.sans(16, .regular, relativeTo: .callout))
                    .foregroundStyle(Theme.textDim)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text("TRY ASKING")
                .font(Theme.sans(11, .bold, relativeTo: .caption2))
                .tracking(1.5)
                .foregroundStyle(Theme.accent)
                .padding(.top, 4)
            ForEach(suggestions, id: \.self) { s in
                Button {
                    prompt = s
                    submit()
                } label: {
                    HStack(spacing: 12) {
                        Text(s)
                            .font(Theme.sans(16, .medium, relativeTo: .callout))
                            .foregroundStyle(Theme.text)
                            .multilineTextAlignment(.leading)
                        Spacer(minLength: 8)
                        Image(systemName: "arrow.up.right")
                            .font(Theme.sans(13, .bold, relativeTo: .footnote))
                            .foregroundStyle(Theme.accent)
                    }
                    .padding(16)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .ledgerCard()
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.top, 20)
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            Button {
                if voice.isRecording { submitAfterVoice = true }
                Task { await voice.toggle() }
            } label: {
                Image(systemName: voice.isRecording ? "waveform" : "mic.fill")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(voice.isRecording ? Theme.text : Theme.accent)
                    .symbolEffect(.variableColor.iterative, isActive: voice.isRecording)
                    .frame(width: 44, height: 44)
                    .background(voice.isRecording ? AnyShapeStyle(Theme.danger) : AnyShapeStyle(Theme.raisedHigh), in: Circle())
                    .overlay(Circle().strokeBorder(Theme.hairline, lineWidth: 0.5))
            }
            .disabled(session.isRunning)

            TextField("", text: $prompt, prompt: Text(voice.isRecording ? "Listening…" : "Ask Ledger…").foregroundStyle(Theme.textFaint), axis: .vertical)
                .lineLimit(1...4)
                .focused($promptFocused)
                .foregroundStyle(Theme.text)
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                .background(Theme.raisedHigh, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .strokeBorder(promptFocused ? Theme.accent.opacity(0.6) : Theme.hairline, lineWidth: promptFocused ? 1 : 0.5))
                .submitLabel(.send)
                .onSubmit(submit)

            if session.isRunning {
                Button { Task { await session.cancel() } } label: {
                    Image(systemName: "stop.fill")
                        .font(.system(size: 15, weight: .bold))
                        .foregroundStyle(Theme.text)
                        .frame(width: 44, height: 44)
                        .background(Theme.danger, in: Circle())
                }
            } else {
                let empty = prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                Button(action: submit) {
                    Image(systemName: "arrow.up")
                        .font(.system(size: 17, weight: .bold))
                        .foregroundStyle(Theme.accentDeep)
                        .frame(width: 44, height: 44)
                        .background(Theme.pearl, in: Circle())
                        .opacity(empty ? 0.3 : 1)
                        .glow(Theme.accent, radius: 10, strength: empty ? 0 : 0.8)
                }
                .disabled(empty)
            }
        }
        .padding(.horizontal)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background {
            LinearGradient(colors: [Theme.ink.opacity(0), Theme.ink.opacity(0.9), Theme.ink],
                           startPoint: .top, endPoint: .init(x: 0.5, y: 0.45))
                .ignoresSafeArea()
        }
    }

    private var connectionDot: some View {
        let (color, label): (Color, String) = switch session.connection {
        case .connected: (Theme.success, "Live")
        case .connecting: (Theme.warning, "Connecting")
        case .disconnected: (Theme.textFaint, "Offline")
        case .failed: (Theme.danger, "Offline")
        }
        return Button { Task { await session.connect() } } label: {
            HStack(spacing: 6) {
                Circle().fill(color).frame(width: 7, height: 7)
                    .shadow(color: color.opacity(0.9), radius: 4)
                Text(label)
                    .font(Theme.sans(12, .semibold, relativeTo: .caption))
                    .foregroundStyle(Theme.text)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(Theme.raised.opacity(0.85), in: Capsule())
            .overlay(Capsule().strokeBorder(Theme.hairline, lineWidth: 0.5))
        }
        .buttonStyle(.plain)
    }

    private func submit() {
        let text = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        promptFocused = false
        prompt = ""
        Speaker.shared.stop()
        Task { await session.run(text) }
    }
}

struct SettingsView: View {
    @AppStorage("serverURL") private var serverURL = "ws://Swapnils-Den.local:8000/ws"
    @AppStorage("speakResults") private var speakResults = true
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Toggle("Read answers aloud", isOn: $speakResults)
                }
                Section {
                    TextField("ws://192.168.1.10:8000/ws", text: $serverURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                } header: {
                    Text("Agent server")
                } footer: {
                    Text("Simulator: ws://localhost:8000/ws. iPhone: use the URL printed by server/run.sh.")
                }
                connectionSection
            }
            .scrollContentBackground(.hidden)
            .ledgerBackground()
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") {
                        if session.connection != .connected { session.disconnect() }
                        dismiss()
                    }
                }
            }
        }
    }

    private var session: AgentSession { AgentSession.shared }

    private var statusLine: String {
        switch session.connection {
        case .connected: "Connected"
        case .connecting: "Connecting…"
        case .disconnected: "Not connected"
        case .failed(let why): "Failed: \(why)"
        }
    }

    private var connectionSection: some View {
        Section {
            Button("Test connection") {
                Task {
                    session.disconnect()
                    session.trace("— test from Settings —")
                    await session.connect()
                }
            }
            .disabled(session.connection == .connecting)
            Text(statusLine)
                .font(Theme.sans(13, .regular, relativeTo: .footnote))
                .foregroundStyle(session.connection == .connected ? Theme.success : Theme.textDim)
            if session.log.isEmpty {
                Text("No log yet").font(Theme.sans(12, .regular, relativeTo: .caption)).foregroundStyle(.secondary)
            } else {
                ForEach(Array(session.log.suffix(60).enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(.caption2.monospaced())
                        .foregroundStyle(line.contains("HINT") || line.contains("fail") ? Theme.danger : Theme.text)
                        .textSelection(.enabled)
                }
            }
            HStack {
                Button("Copy log") { UIPasteboard.general.string = session.log.joined(separator: "\n") }
                Spacer()
                Button("Clear", role: .destructive) { session.clearLog() }
            }
            .buttonStyle(.borderless)
        } header: {
            Text("Connection")
        }
    }
}
