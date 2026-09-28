import SwiftUI

/// Approvals tab: every payment Ledger wants to make waits here until the owner decides.
/// The agent is paused on each one; money only moves after "Approve".
struct ApprovalsView: View {
    @State private var session = AgentSession.shared
    @State private var confirming: ApprovalItem?
    @State private var rejecting: ApprovalItem?

    private var history: [ApprovalItem] { session.approvals.filter { $0.status != .pending } }

    var body: some View {
        NavigationStack {
            Group {
                if session.approvals.isEmpty {
                    VStack(spacing: 16) {
                        ShieldMiniature()
                        Text("No payments to approve")
                            .font(Theme.display(24))
                            .foregroundStyle(Theme.text)
                        Text("When Ledger wants to refund or settle a dispute, it stops and asks you here first.")
                            .font(Theme.sans(16, .regular, relativeTo: .callout))
                            .foregroundStyle(Theme.textDim)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 40)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            if !session.pendingApprovals.isEmpty {
                                sectionHeader("Waiting for you", count: session.pendingApprovals.count)
                                ForEach(session.pendingApprovals) { item in
                                    PendingApprovalCard(item: item,
                                                        onApprove: { confirming = item },
                                                        onReject: { rejecting = item })
                                }
                                Text("Ledger is paused until you decide. Unanswered requests expire and nothing is paid.")
                                    .font(Theme.sans(12, .regular, relativeTo: .caption))
                                    .foregroundStyle(Theme.textFaint)
                            }
                            if !history.isEmpty {
                                sectionHeader("History", count: nil).padding(.top, 8)
                                VStack(spacing: 0) {
                                    ForEach(Array(history.enumerated()), id: \.element.id) { index, item in
                                        ApprovalHistoryRow(item: item)
                                        if index < history.count - 1 { Divider().overlay(Theme.hairline) }
                                    }
                                }
                                .padding(.horizontal, 14)
                                .ledgerCard()
                            }
                        }
                        .padding(.horizontal)
                        .padding(.bottom, 24)
                    }
                }
            }
            .safeAreaInset(edge: .top, spacing: 0) {
                HStack {
                    Text("Approvals")
                        .font(Theme.display(36, .bold))
                        .foregroundStyle(Theme.pearl)
                        .glow(Theme.accent, radius: 14, strength: 0.7)
                    Spacer()
                }
                .padding(.horizontal)
                .padding(.top, 6)
                .padding(.bottom, 12)
            }
            .ledgerBackground()
            .toolbar(.hidden, for: .navigationBar)
            .confirmationDialog(confirmTitle, isPresented: confirmShown, titleVisibility: .visible) {
                if let item = confirming {
                    Button("Approve and pay") {
                        Task { await session.respond(to: item, approved: true) }
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text(confirming?.request.title ?? "")
            }
            .sheet(item: $rejecting) { item in
                RejectReasonSheet(item: item) { note in
                    Task { await session.respond(to: item, approved: false, note: note) }
                }
            }
        }
    }

    private func sectionHeader(_ title: String, count: Int?) -> some View {
        HStack(spacing: 8) {
            Text(title.uppercased())
                .font(Theme.sans(12, .bold, relativeTo: .caption))
                .tracking(1.2)
                .foregroundStyle(Theme.accent)
            if let count {
                Text("\(count)")
                    .font(Theme.sans(11, .bold, relativeTo: .caption2))
                    .foregroundStyle(Theme.onAccent)
                    .padding(.horizontal, 7)
                    .padding(.vertical, 1)
                    .background(Theme.accentGradient, in: Capsule())
            }
        }
    }

    private var confirmShown: Binding<Bool> {
        Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } })
    }

    private var confirmTitle: String {
        guard let item = confirming, let amount = item.request.amount else { return "Approve payment?" }
        let money = amount.formatted(.currency(code: "USD"))
        return item.buyer.map { "Pay \(money) to \($0)?" } ?? "Pay \(money)?"
    }
}

/// Everything the owner needs to decide one payment: what, who, why, evidence, time left.
private struct PendingApprovalCard: View {
    let item: ApprovalItem
    let onApprove: () -> Void
    let onReject: () -> Void

    private var event: AgentEvent { item.request }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .firstTextBaseline) {
                Label(event.caseId ?? "Payment", systemImage: "hand.raised.fill")
                    .font(Theme.sans(12, .bold, relativeTo: .caption))
                    .tracking(0.6)
                    .foregroundStyle(Theme.warning)
                Spacer()
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    let left = max(0, item.deadline.timeIntervalSince(context.date))
                    Text(left > 0 ? "Expires in \(Duration.seconds(left).formatted(.time(pattern: .minuteSecond)))" : "Expiring…")
                        .font(Theme.sans(12, .regular, relativeTo: .caption).monospacedDigit())
                        .foregroundStyle(left < 120 ? Theme.danger : Theme.textDim)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 3)
                        .background(Theme.raisedHigh, in: Capsule())
                }
            }

            if let amount = event.amount {
                Text(amount, format: .currency(code: "USD"))
                    .font(Theme.display(42, .bold))
                    .foregroundStyle(Theme.pearl)
                    .glow(Theme.accent, radius: 12, strength: 0.6)
            }
            Text(event.title)
                .font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                .foregroundStyle(Theme.text)

            if let facts = event.facts, !facts.isEmpty {
                Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
                    ForEach(facts, id: \.self) { fact in
                        GridRow {
                            Text(fact.label).foregroundStyle(Theme.textFaint)
                            Text(fact.value).foregroundStyle(Theme.text).fixedSize(horizontal: false, vertical: true)
                        }
                        .font(Theme.sans(13, .regular, relativeTo: .footnote))
                    }
                }
            }

            if let reason = event.detail, !reason.isEmpty {
                section("Why Ledger recommends this") {
                    Text(reason).font(Theme.sans(16, .regular, relativeTo: .callout)).foregroundStyle(Theme.text)
                }
            }

            if let evidence = event.evidence, !evidence.isEmpty {
                section("Evidence found") {
                    ForEach(evidence, id: \.self) { clue in
                        Label(clue, systemImage: "magnifyingglass")
                            .font(Theme.sans(13, .regular, relativeTo: .footnote))
                            .foregroundStyle(Theme.textDim)
                    }
                }
            }

            HStack(spacing: 12) {
                Button(action: onReject) {
                    Label("Reject", systemImage: "xmark")
                        .font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                        .foregroundStyle(Theme.danger)
                        .padding(.vertical, 13)
                        .frame(maxWidth: .infinity)
                        .overlay(Capsule().strokeBorder(Theme.danger.opacity(0.6), lineWidth: 1))
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                Button(action: onApprove) {
                    Label("Approve", systemImage: "checkmark")
                }
                .buttonStyle(PrimaryButtonStyle())
            }
            .padding(.top, 4)
        }
        .padding(18)
        .ledgerCard(accent: Theme.accent, radius: 20)
    }

    private func section<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(Theme.sans(11, .bold, relativeTo: .caption2))
                .tracking(0.8)
                .textCase(.uppercase)
                .foregroundStyle(Theme.accent.opacity(0.85))
            content()
        }
    }
}

/// Owner's reason travels back to the agent, which records it and follows it.
private struct RejectReasonSheet: View {
    let item: ApprovalItem
    let onReject: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var reason = ""

    private let quickReasons = [
        "Amount is too high",
        "Need more evidence first",
        "Contest the dispute instead",
        "I'll handle this myself",
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(item.request.title).font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                } footer: {
                    Text("Nothing is paid. Ledger logs the case as pending your decision and follows your reason.")
                }
                Section("Why? (optional)") {
                    ForEach(quickReasons, id: \.self) { option in
                        Button {
                            reason = option
                        } label: {
                            HStack {
                                Text(option).foregroundStyle(Theme.text)
                                Spacer()
                                if reason == option { Image(systemName: "checkmark").foregroundStyle(.tint) }
                            }
                        }
                    }
                    TextField("Or type your own reason", text: $reason, axis: .vertical)
                        .lineLimit(1...3)
                }
            }
            .scrollContentBackground(.hidden)
            .ledgerBackground()
            .navigationTitle("Reject payment")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Reject", role: .destructive) {
                        onReject(reason.trimmingCharacters(in: .whitespacesAndNewlines))
                        dismiss()
                    }
                    .tint(Theme.danger)
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

private struct ApprovalHistoryRow: View {
    let item: ApprovalItem

    private var style: (String, Color, String) {
        switch item.status {
        case .approved: ("checkmark.seal.fill", Theme.success, "Approved")
        case .rejected: ("xmark.seal.fill", Theme.danger, "Rejected")
        case .expired: ("clock.badge.xmark", Theme.textFaint, "Expired, nothing paid")
        case .pending: ("hourglass", Theme.warning, "Waiting")
        }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: style.0)
                .foregroundStyle(style.1)
                .font(Theme.sans(20, .regular, relativeTo: .title3))
            VStack(alignment: .leading, spacing: 3) {
                Text(item.request.title)
                    .font(Theme.sans(15, .semibold, relativeTo: .subheadline))
                    .foregroundStyle(Theme.text)
                HStack(spacing: 6) {
                    Text(style.2).foregroundStyle(style.1)
                    if let at = item.decidedAt {
                        Text(at, style: .time).foregroundStyle(Theme.textFaint)
                    }
                }
                .font(Theme.sans(12, .regular, relativeTo: .caption))
                if !item.note.isEmpty {
                    Text("“\(item.note)”")
                        .font(Theme.sans(12, .regular, relativeTo: .caption).italic())
                        .foregroundStyle(Theme.textDim)
                }
            }
        }
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}
