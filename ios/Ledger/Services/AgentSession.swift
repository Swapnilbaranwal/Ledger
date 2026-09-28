import Foundation
import Observation
import UIKit

/// Owns the WebSocket to the agent server and the live timeline state.
@MainActor
@Observable
final class AgentSession {
    static let shared = AgentSession()

    enum Connection: Equatable { case disconnected, connecting, connected, failed(String) }

    /// The current question's timeline (Ledger tab).
    private(set) var events: [AgentEvent] = []
    /// Finished questions this session, newest first (History tab).
    private(set) var history: [RunRecord] = []
    private(set) var connection: Connection = .disconnected
    private(set) var isRunning = false
    private(set) var statusText: String?
    private(set) var servicesUsed: [String] = []
    private(set) var toolCallCount = 0
    /// Every payment Ledger asked about this session: waiting ones first in the Approvals tab.
    private(set) var approvals: [ApprovalItem] = []
    var pendingApprovals: [ApprovalItem] { approvals.filter { $0.status == .pending } }
    var finalResult: AgentEvent?

    /// Set by the Siri intent; ContentView picks it up.
    var queuedPrompt: String?

    /// Connection log shown in Settings, so you can debug on the phone without Xcode.
    private(set) var log: [String] = []

    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?

    var serverURL: URL {
        let raw = UserDefaults.standard.string(forKey: "serverURL") ?? "ws://Swapnils-Den.local:8000/ws"
        return URL(string: raw) ?? URL(string: "ws://Swapnils-Den.local:8000/ws")!
    }

    // MARK: - Debug log

    func trace(_ line: String) {
        let stamp = Date.now.formatted(date: .omitted, time: .standard)
        print("[Ledger] \(line)")
        log.append("\(stamp)  \(line)")
        if log.count > 200 { log.removeFirst(log.count - 200) }
    }

    func clearLog() { log.removeAll() }

    func clearHistory() { history.removeAll() }

    /// Move the current question and its steps into History (once).
    private func archiveCurrentRun() {
        guard let record = RunRecord(events: events, services: servicesUsed, toolCalls: toolCallCount),
              !history.contains(where: { $0.id == record.id }) else { return }
        history.insert(record, at: 0)
    }

    /// Plain-English explanation of the usual reasons the phone can't reach the Mac.
    private func hint(for error: Error) -> String {
        let ns = error as NSError
        switch ns.code {
        case NSURLErrorCannotConnectToHost:
            return "Server refused the connection. Is uvicorn running, and listening on IPv4 AND IPv6? Start it with server/run.sh (not --host 0.0.0.0)."
        case NSURLErrorCannotFindHost, NSURLErrorDNSLookupFailed:
            return "Hostname not found. Use the Mac's IP address printed by server/run.sh."
        case NSURLErrorTimedOut:
            return "Timed out. Phone and Mac are probably on different networks, or the Mac firewall is blocking Python."
        case NSURLErrorNotConnectedToInternet, NSURLErrorNetworkConnectionLost:
            return "No network path. Check Wi-Fi and Settings → Privacy & Security → Local Network → Ledger."
        case NSURLErrorAppTransportSecurityRequiresSecureConnection:
            return "Blocked by App Transport Security (Info.plist)."
        case NSURLErrorBadServerResponse:
            return "Something answered but it isn't the Ledger server. Check the port and the /ws path."
        default:
            return "\(ns.domain) \(ns.code)"
        }
    }

    // MARK: - Connection

    func connect() async {
        trace("connect() tapped — current state: \(connection)")
        trace("UserDefaults serverURL raw: \(UserDefaults.standard.string(forKey: "serverURL") ?? "<nil, using default>")")
        trace("resolved serverURL: \(serverURL.absoluteString)")
        if connection == .connected || connection == .connecting {
            trace("connect() skipped — already \(connection)")
            return
        }
        connection = .connecting
        let task = URLSession.shared.webSocketTask(with: serverURL)
        trace("webSocketTask created, resuming…")
        socket = task
        task.resume()
        receiveTask?.cancel()
        receiveTask = Task { [weak self] in await self?.receiveLoop(task) }
        // `connected` is confirmed by the server's "hello" event; time out otherwise.
        var waited = 0
        while connection == .connecting && waited < 40 {
            try? await Task.sleep(for: .milliseconds(100))
            waited += 1
        }
        trace("connect() wait finished after \(waited * 100)ms — state: \(connection), task.state: \(task.state.rawValue), task.error: \(String(describing: task.error))")
        if connection == .connecting {
            trace("TIMEOUT — no 'hello' event received within 4s")
            fail("Could not reach \(serverURL.absoluteString)")
        }
    }

    func disconnect() {
        trace("disconnect() called")
        receiveTask?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        connection = .disconnected
        isRunning = false
        expirePending()
    }

    private func fail(_ message: String) {
        trace("fail(): \(message)")
        expirePending()
        connection = .failed(message)
        isRunning = false
        statusText = nil
        socket?.cancel()
        socket = nil
    }

    private func receiveLoop(_ task: URLSessionWebSocketTask) async {
        let decoder = JSONDecoder()
        trace("receiveLoop started")
        while !Task.isCancelled {
            do {
                let message = try await task.receive()
                let data: Data
                switch message {
                case .string(let s):
                    trace("received string: \(s.prefix(300))")
                    data = Data(s.utf8)
                case .data(let d):
                    trace("received data: \(d.count) bytes")
                    data = d
                @unknown default: continue
                }
                do {
                    let event = try decoder.decode(AgentEvent.self, from: data)
                    handle(event)
                } catch {
                    trace("DECODE FAILED: \(error)")
                }
            } catch {
                let ns = error as NSError
                trace("receive error (cancelled=\(Task.isCancelled)): \(error) — domain: \(ns.domain) code: \(ns.code) userInfo: \(ns.userInfo)")
                if !Task.isCancelled {
                    let why = hint(for: error)
                    trace("HINT: \(why)")
                    fail(why)
                }
                return
            }
        }
        trace("receiveLoop exited (cancelled)")
    }

    // MARK: - Actions

    func run(_ prompt: String) async {
        guard !isRunning else { return }
        await connect()
        guard connection == .connected else { return }
        archiveCurrentRun()  // an interrupted run still lands in History
        events.removeAll()
        servicesUsed.removeAll()
        toolCallCount = 0
        finalResult = nil
        isRunning = true
        statusText = "Starting…"
        await send(.run(prompt: prompt))
    }

    func respond(to item: ApprovalItem, approved: Bool, note: String = "") async {
        guard let index = approvals.firstIndex(where: { $0.id == item.id }),
              approvals[index].status == .pending else { return }
        approvals[index].status = approved ? .approved : .rejected
        approvals[index].note = note
        approvals[index].decidedAt = .now
        UINotificationFeedbackGenerator().notificationOccurred(approved ? .success : .warning)
        await send(.approval(id: item.id, approved: approved, note: note))
    }

    /// Waiting approvals can't be answered once the socket that asked is gone.
    private func expirePending() {
        for i in approvals.indices where approvals[i].status == .pending {
            approvals[i].status = .expired
            approvals[i].decidedAt = .now
        }
    }

    func cancel() async { await send(.cancel) }

    private func send(_ message: ClientMessage) async {
        guard let socket, let data = try? JSONEncoder().encode(message),
              let text = String(data: data, encoding: .utf8) else { return }
        do { try await socket.send(.string(text)) } catch { fail(error.localizedDescription) }
    }

    // MARK: - Event handling

    private func handle(_ event: AgentEvent) {
        trace("handle event: \(event.type) — \(event.title)")
        switch event.type {
        case .hello:
            trace("hello received — marking connected")
            connection = .connected
        case .status:
            statusText = event.title
        case .toolCall:
            toolCallCount += 1
            statusText = event.title
            if let s = event.service, !servicesUsed.contains(s) { servicesUsed.append(s) }
        case .approvalRequest:
            if let item = ApprovalItem(event) { approvals.insert(item, at: 0) }
            statusText = "Waiting for your approval (Approvals tab)"
            UINotificationFeedbackGenerator().notificationOccurred(.warning)
        case .final:
            finalResult = event
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        case .approvalResolved:
            if let id = event.approvalId, let i = approvals.firstIndex(where: { $0.id == id }) {
                approvals[i].status = event.expired == true ? .expired : (event.approved == true ? .approved : .rejected)
                if let note = event.detail, !note.isEmpty { approvals[i].note = note }
                approvals[i].decidedAt = approvals[i].decidedAt ?? .now
            }
        case .runFinished:
            isRunning = false
            statusText = nil
            archiveCurrentRun()
        case .error:
            UINotificationFeedbackGenerator().notificationOccurred(.error)
        default:
            break
        }
        if event.isTimelineItem { events.append(event) }
    }
}

/// A payment the agent wants to make, and what the owner decided.
struct ApprovalItem: Identifiable, Equatable {
    enum Status { case pending, approved, rejected, expired }

    let id: String
    let request: AgentEvent
    let receivedAt: Date
    var status: Status = .pending
    var note = ""
    var decidedAt: Date?

    init?(_ event: AgentEvent) {
        guard let id = event.approvalId else { return nil }
        self.id = id
        self.request = event
        self.receivedAt = .now
    }

    var deadline: Date { receivedAt.addingTimeInterval(TimeInterval(request.expiresIn ?? 900)) }
    var buyer: String? { request.facts?.first { $0.label == "Buyer" }?.value }
}

/// One finished question: what was asked, the answer, and the steps Ledger took.
struct RunRecord: Identifiable {
    let id: String          // the run_started event id
    let question: String
    let answer: String?
    let askedAt: Date
    let services: [String]
    let toolCalls: Int
    let steps: [AgentEvent]  // the short list: calls, evidence, decisions, links, errors

    init?(events: [AgentEvent], services: [String], toolCalls: Int) {
        guard let start = events.first(where: { $0.type == .runStarted }) else { return nil }
        id = start.id
        question = start.title
        answer = events.last(where: { $0.type == .final })?.detail
        askedAt = start.ts.flatMap { ISO8601DateFormatter.withFraction.date(from: $0) } ?? .now
        self.services = services
        self.toolCalls = toolCalls
        steps = events.filter { [.toolCall, .finding, .approvalResolved, .link, .error].contains($0.type) }
    }
}

private extension ISO8601DateFormatter {
    static let withFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
}
