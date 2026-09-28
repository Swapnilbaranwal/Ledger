import SwiftUI

/// One card in the live agent timeline.
struct EventRow: View {
    let event: AgentEvent
    @State private var expanded = false

    var body: some View {
        if event.type == .link, let url = event.url.flatMap(URL.init(string:)) {
            Link(destination: url) { card }.buttonStyle(.plain)
        } else if event.type == .final {
            finalCard
        } else {
            card
        }
    }

    // MARK: - Cards

    private var card: some View {
        HStack(alignment: .top, spacing: 12) {
            icon
            VStack(alignment: .leading, spacing: 5) {
                HStack(spacing: 6) {
                    Text(kindLabel)
                        .font(Theme.sans(11, .bold, relativeTo: .caption2))
                        .tracking(0.8)
                        .textCase(.uppercase)
                        .foregroundStyle(tint)
                    if let via = event.via, event.type == .toolCall {
                        Text(via == "mock" ? "demo data" : "live")
                            .font(Theme.sans(11, .semibold, relativeTo: .caption2))
                            .foregroundStyle(via == "mock" ? Theme.textFaint : Theme.success)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 1)
                            .background((via == "mock" ? Theme.textFaint : Theme.success).opacity(0.12), in: Capsule())
                    }
                }
                Text(event.title)
                    .font(event.type == .runStarted ? Theme.display(19) : Theme.sans(15, .semibold, relativeTo: .subheadline))
                    .foregroundStyle(Theme.text)
                    .fixedSize(horizontal: false, vertical: true)

                if event.type == .link {
                    Text("Open")
                        .font(Theme.sans(12, .bold, relativeTo: .caption))
                        .foregroundStyle(Theme.accentDeep)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 3)
                        .background(Theme.pearl, in: Capsule())
                        .glow(Theme.accent, radius: 6, strength: 0.5)
                        .padding(.top, 2)
                } else if let detail = event.detail, !detail.isEmpty, event.type != .finding {
                    Text(detail)
                        .font(isCode ? .caption.monospaced() : Theme.sans(15, relativeTo: .callout))
                        .foregroundStyle(Theme.textDim)
                        .lineLimit(expanded ? nil : (isCode ? 3 : 6))
                        .fixedSize(horizontal: false, vertical: true)
                        .onTapGesture { withAnimation(.snappy) { expanded.toggle() } }
                }
            }
            Spacer(minLength: 0)
            if event.type == .link {
                Image(systemName: "arrow.up.right")
                    .font(Theme.sans(13, .bold, relativeTo: .footnote))
                    .foregroundStyle(Theme.accent)
            }
        }
        .padding(14)
        .ledgerCard(accent: accented ? tint : nil)
        .overlay(alignment: .leading) {
            if accented {
                UnevenRoundedRectangle(topLeadingRadius: 16, bottomLeadingRadius: 16)
                    .fill(tint)
                    .frame(width: 3)
            }
        }
    }

    /// The answer is the point of the whole run, so it gets the hero treatment.
    private var finalCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                Text("Ledger's answer")
                    .font(Theme.sans(12, .bold, relativeTo: .caption))
                    .tracking(1)
                    .textCase(.uppercase)
                Spacer()
                if let calls = event.toolCalls, calls > 0 {
                    Text("\(calls) API calls")
                        .font(Theme.sans(11, .semibold, relativeTo: .caption2).monospacedDigit())
                }
            }
            .foregroundStyle(Theme.accentLight)
            Text(event.detail ?? event.title)
                .font(Theme.sans(17, .medium))
                .foregroundStyle(Theme.text)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(18)
        .background {
            RoundedRectangle(cornerRadius: 20, style: .continuous)
                .fill(LinearGradient(colors: [Color(hex: 0x3A36A8), Color(hex: 0x1A1B52), Theme.raised],
                                     startPoint: .topLeading, endPoint: .bottomTrailing))
        }
        .overlay(RoundedRectangle(cornerRadius: 20, style: .continuous)
            .strokeBorder(LinearGradient(colors: [.white.opacity(0.8), Theme.accent.opacity(0.4), .white.opacity(0.1)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 1))
        .glow(Theme.accent, radius: 18, strength: 0.45)
    }

    @ViewBuilder private var icon: some View {
        if [.toolCall, .link].contains(event.type) && event.service != nil {
            ServiceGlyph(service: event.service, size: 34)
        } else {
            symbolIcon
        }
    }

    private var symbolIcon: some View {
        Image(systemName: iconName)
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(tint)
            .frame(width: 34, height: 34)
            .background(tint.opacity(0.14), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(tint.opacity(0.25), lineWidth: 0.5))
    }

    // MARK: - Styling per event

    private var isCode: Bool { event.type == .toolCall || event.type == .toolResult }

    private var accented: Bool {
        [.approvalRequest, .approvalResolved, .error, .finding].contains(event.type)
    }

    private var kindLabel: String {
        switch event.type {
        case .runStarted: return "You asked"
        case .thought: return "Reasoning"
        case .decision: return "Tool selection"
        case .finding: return "Evidence · " + (event.detail ?? "case")
        case .toolCall: return ServiceStyle.name(event.service) + " call"
        case .toolResult: return ServiceStyle.name(event.service) + " result"
        case .approvalRequest: return "Needs your approval"
        case .approvalResolved: return "Your decision"
        case .final: return "Ledger's answer"
        case .link: return "Created in " + ServiceStyle.name(event.service)
        case .error: return "Error"
        default: return ""
        }
    }

    private var tint: Color {
        switch event.type {
        case .toolCall, .toolResult:
            return event.ok == false ? Theme.warning : ServiceStyle.color(event.service)
        case .link: return ServiceStyle.color(event.service)
        case .runStarted: return Theme.accent
        case .thought: return Theme.accentLight
        case .decision: return Theme.textDim
        case .finding:
            switch event.pointsTo {
            case "merchant": return Theme.success
            case "fraud": return Theme.danger
            case "buyer": return Theme.warning
            default: return Theme.textDim
            }
        case .approvalRequest: return Theme.warning
        case .approvalResolved: return event.approved == true ? Theme.success : Theme.danger
        case .final: return Theme.accent
        case .error: return Theme.danger
        default: return Theme.accent
        }
    }

    private var iconName: String {
        switch event.type {
        case .runStarted: "person.fill"
        case .thought: "brain.head.profile"
        case .decision: "arrow.triangle.branch"
        case .finding: "magnifyingglass"
        case .toolCall: ServiceStyle.icon(event.service)
        case .toolResult: event.ok == false ? "exclamationmark.triangle.fill" : "checkmark"
        case .approvalRequest: "hand.raised.fill"
        case .approvalResolved: event.approved == true ? "checkmark.seal.fill" : "xmark.seal.fill"
        case .final: "sparkles"
        case .link: ServiceStyle.icon(event.service)
        case .error: "xmark.octagon.fill"
        default: "circle"
        }
    }
}

// MARK: - History tab

/// Past questions this session; tap one to see, in a few lines, what Ledger did for it.
struct HistoryView: View {
    @State private var session = AgentSession.shared

    var body: some View {
        NavigationStack {
            Group {
                if session.history.isEmpty {
                    VStack(spacing: 14) {
                        Image(systemName: "clock.arrow.circlepath")
                            .font(.system(size: 30, weight: .semibold))
                            .foregroundStyle(Theme.accentDeep)
                            .frame(width: 72, height: 72)
                            .background(Theme.pearl, in: Circle())
                            .glow(Theme.accent, radius: 16, strength: 0.7)
                        Text("No questions yet")
                            .font(Theme.display(24))
                            .foregroundStyle(Theme.text)
                        Text("Every question you ask appears here with what Ledger did for it.")
                            .font(Theme.sans(15, relativeTo: .callout))
                            .foregroundStyle(Theme.textDim)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 40)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(session.history) { record in
                                NavigationLink(value: record.id) { HistoryRow(record: record) }
                                    .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal)
                        .padding(.bottom, 24)
                    }
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                HStack {
                    Text("History")
                        .font(Theme.display(36, .bold))
                        .foregroundStyle(Theme.pearl)
                        .glow(Theme.accent, radius: 14, strength: 0.7)
                    Spacer()
                    if !session.history.isEmpty {
                        Button("Clear") { session.clearHistory() }
                            .font(Theme.sans(15, .semibold))
                            .foregroundStyle(Theme.accentLight)
                    }
                }
                .padding(.horizontal)
                .padding(.top, 6)
                .padding(.bottom, 12)
            }
            .ledgerBackground()
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: String.self) { id in
                if let record = session.history.first(where: { $0.id == id }) {
                    HistoryDetail(record: record)
                }
            }
        }
    }
}

private struct HistoryRow: View {
    let record: RunRecord

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(record.question)
                .font(Theme.sans(16, .semibold))
                .foregroundStyle(Theme.text)
                .lineLimit(2)
                .multilineTextAlignment(.leading)
            if let answer = record.answer {
                Text(answer)
                    .font(Theme.sans(14, relativeTo: .subheadline))
                    .foregroundStyle(Theme.textDim)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
            }
            HStack(spacing: 6) {
                ForEach(record.services, id: \.self) { ServiceGlyph(service: $0, size: 18) }
                Text("\(record.steps.count) steps")
                    .font(Theme.sans(12, .medium, relativeTo: .caption))
                    .foregroundStyle(Theme.textFaint)
                    .padding(.leading, record.services.isEmpty ? 0 : 4)
                Spacer()
                Text(record.askedAt, style: .time)
                    .font(Theme.sans(12, relativeTo: .caption))
                    .foregroundStyle(Theme.textFaint)
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Theme.accentLight)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .ledgerCard()
    }
}

/// One question: the answer, then each step on a single line.
private struct HistoryDetail: View {
    let record: RunRecord

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 6) {
                    Text(record.question)
                        .font(Theme.display(24))
                        .foregroundStyle(Theme.text)
                    Text("\(record.askedAt.formatted(date: .omitted, time: .shortened)) · \(record.toolCalls) API calls")
                        .font(Theme.sans(12, .medium, relativeTo: .caption))
                        .foregroundStyle(Theme.textFaint)
                }
                if let answer = record.answer {
                    Text(answer)
                        .font(Theme.sans(16, .medium))
                        .foregroundStyle(Theme.text)
                        .lineSpacing(3)
                        .padding(16)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .ledgerCard(accent: Theme.accent)
                }
                Text("WHAT LEDGER DID")
                    .font(Theme.sans(12, .bold, relativeTo: .caption))
                    .tracking(1.2)
                    .foregroundStyle(Theme.accentLight)
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(record.steps.enumerated()), id: \.element.id) { index, step in
                        HistoryStep(step: step)
                        if index < record.steps.count - 1 { Divider().overlay(Theme.hairline) }
                    }
                    if record.steps.isEmpty {
                        Text("No actions: Ledger answered directly.")
                            .font(Theme.sans(14))
                            .foregroundStyle(Theme.textDim)
                            .padding(.vertical, 12)
                    }
                }
                .padding(.horizontal, 14)
                .ledgerCard()
            }
            .padding(.horizontal)
            .padding(.bottom, 24)
        }
        .ledgerBackground()
        .navigationTitle("Question")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar(.visible, for: .navigationBar)
    }
}

private struct HistoryStep: View {
    let step: AgentEvent

    var body: some View {
        if step.type == .link, let url = step.url.flatMap(URL.init(string:)) {
            Link(destination: url) { row(trailing: "arrow.up.right") }.buttonStyle(.plain)
        } else {
            row(trailing: nil)
        }
    }

    private func row(trailing: String?) -> some View {
        HStack(spacing: 10) {
            leading
            Text(line)
                .font(Theme.sans(14, step.type == .link ? .semibold : .regular, relativeTo: .subheadline))
                .foregroundStyle(step.type == .error ? Theme.danger : Theme.text)
                .lineLimit(2)
            Spacer(minLength: 0)
            if let trailing {
                Image(systemName: trailing)
                    .font(.caption.weight(.bold))
                    .foregroundStyle(Theme.accentLight)
            }
        }
        .padding(.vertical, 10)
    }

    @ViewBuilder private var leading: some View {
        switch step.type {
        case .toolCall, .link:
            ServiceGlyph(service: step.service, size: 22)
        case .finding:
            Image(systemName: "magnifyingglass").symbol(Theme.warning)
        case .approvalResolved:
            Image(systemName: step.approved == true ? "checkmark.seal.fill" : "xmark.seal.fill")
                .symbol(step.approved == true ? Theme.success : Theme.danger)
        default:
            Image(systemName: "xmark.octagon.fill").symbol(Theme.danger)
        }
    }

    private var line: String {
        switch step.type {
        case .finding: return "Evidence: \(step.title)"
        case .link: return "Opened \(step.title)"
        default: return step.title
        }
    }
}

private extension Image {
    func symbol(_ color: Color) -> some View {
        font(.system(size: 12, weight: .bold))
            .foregroundStyle(color)
            .frame(width: 22, height: 22)
            .background(color.opacity(0.15), in: RoundedRectangle(cornerRadius: 7, style: .continuous))
    }
}
