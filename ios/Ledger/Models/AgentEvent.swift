import Foundation

/// One step streamed from the agent server (see server/app/events.py).
struct AgentEvent: Decodable, Identifiable, Equatable {
    enum Kind: String, Decodable {
        case hello, status, runStarted = "run_started", thought, decision, finding
        case toolCall = "tool_call", toolResult = "tool_result"
        case approvalRequest = "approval_request", approvalResolved = "approval_resolved"
        case final, error, runFinished = "run_finished"
        case link
        case unknown

        init(from decoder: Decoder) throws {
            let raw = try decoder.singleValueContainer().decode(String.self)
            self = Kind(rawValue: raw) ?? .unknown
        }
    }

    let type: Kind
    let id: String
    let ts: String?
    let title: String
    let detail: String?
    let service: String?
    let tool: String?
    let via: String?
    let ok: Bool?
    let approvalId: String?
    let amount: Double?
    let approved: Bool?
    let toolCalls: Int?
    let services: [String]?
    let pointsTo: String?
    /// Set on `link` events: the Jira ticket / Notion page / Slack channel the agent just created.
    let url: String?
    /// Approval events: the dispute, key facts for the owner, evidence pinned so far, time to decide.
    let caseId: String?
    let facts: [Fact]?
    let evidence: [String]?
    let expiresIn: Int?
    let expired: Bool?

    struct Fact: Decodable, Equatable, Hashable {
        let label: String
        let value: String
    }

    enum CodingKeys: String, CodingKey {
        case type, id, ts, title, detail, service, tool, via, ok, amount, approved, services, url, facts, evidence, expired
        case caseId = "case"
        case expiresIn = "expires_in"
        case approvalId = "approval_id"
        case toolCalls = "tool_calls"
        case pointsTo = "points_to"
    }

    /// Events worth a card in the timeline (status pings only drive the spinner).
    var isTimelineItem: Bool {
        switch type {
        case .hello, .status, .runFinished, .unknown: return false
        default: return true
        }
    }
}

/// Messages the app sends to the server.
enum ClientMessage: Encodable {
    case run(prompt: String)
    case approval(id: String, approved: Bool, note: String)
    case cancel

    private enum K: String, CodingKey { case type, prompt, approval_id, approved, note }

    func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        switch self {
        case .run(let prompt):
            try c.encode("run", forKey: .type)
            try c.encode(prompt, forKey: .prompt)
        case .approval(let id, let approved, let note):
            try c.encode("approval", forKey: .type)
            try c.encode(id, forKey: .approval_id)
            try c.encode(approved, forKey: .approved)
            try c.encode(note, forKey: .note)
        case .cancel:
            try c.encode("cancel", forKey: .type)
        }
    }
}
