import AppIntents

/// "Hey Siri, chase my invoices with Ledger" → opens the app and starts a run.
struct RunLedgerIntent: AppIntent {
    static let title: LocalizedStringResource = "Run Ledger"
    static let description = IntentDescription("Ask Ledger, your AI COO, for a brief or to investigate disputes.")
    static let openAppWhenRun = true

    @Parameter(title: "Request", default: "Brief me. How's the business doing today?")
    var request: String

    @MainActor
    func perform() async throws -> some IntentResult {
        AgentSession.shared.queuedPrompt = request
        return .result()
    }
}

struct LedgerShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: RunLedgerIntent(),
            phrases: [
                "Brief me with \(.applicationName)",
                "How's business \(.applicationName)",
                "Run \(.applicationName)",
            ],
            shortTitle: "Business brief",
            systemImageName: "waveform"
        )
        AppShortcut(
            intent: InvestigateDisputesIntent(),
            phrases: ["Investigate disputes with \(.applicationName)"],
            shortTitle: "Investigate disputes",
            systemImageName: "magnifyingglass"
        )
    }
}

/// "Hey Siri, investigate disputes with Ledger"
struct InvestigateDisputesIntent: AppIntent {
    static let title: LocalizedStringResource = "Investigate disputes"
    static let openAppWhenRun = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AgentSession.shared.queuedPrompt = "Investigate today's PayPal disputes and handle them."
        return .result()
    }
}
