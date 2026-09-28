import AVFoundation
import Observation
import Speech

/// Push-to-talk: tap the mic, speak, tap again. Live transcript is published as you talk.
@MainActor
@Observable
final class VoiceInput {
    private(set) var transcript = ""
    private(set) var isRecording = false
    var errorMessage: String?

    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-IN")) ?? SFSpeechRecognizer()
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    func toggle() async {
        if isRecording { stop() } else { await start() }
    }

    func start() async {
        Speaker.shared.stop()
        let speechOK = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        let micOK = await AVAudioApplication.requestRecordPermission()
        guard speechOK, micOK else {
            errorMessage = "Allow Microphone and Speech Recognition in Settings to talk to Ledger."
            return
        }
        guard let recognizer, recognizer.isAvailable else {
            errorMessage = "Speech recognition isn't available right now."
            return
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .defaultToSpeaker])
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            request = req

            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0),
                             block: Self.makeTap(req))
            engine.prepare()
            try engine.start()

            transcript = ""
            isRecording = true
            task = recognizer.recognitionTask(with: req, resultHandler: Self.makeHandler(self))
        } catch {
            errorMessage = error.localizedDescription
            stop()
        }
    }

    // Audio + speech callbacks arrive on background threads: build them outside the main actor.
    nonisolated private static func makeTap(_ req: SFSpeechAudioBufferRecognitionRequest) -> AVAudioNodeTapBlock {
        { buffer, _ in req.append(buffer) }
    }

    nonisolated private static func makeHandler(_ owner: VoiceInput) -> (SFSpeechRecognitionResult?, Error?) -> Void {
        { [weak owner] result, error in
            let text = result?.bestTranscription.formattedString
            let done = error != nil || (result?.isFinal ?? false)
            Task { @MainActor in
                guard let owner else { return }
                if let text { owner.transcript = text }
                if done { owner.stop() }
            }
        }
    }

    func stop() {
        guard isRecording else { return }
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.finish()
        request = nil
        task = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}

/// Reads Ledger's final answer aloud (the "Jarvis" moment).
@MainActor
final class Speaker {
    static let shared = Speaker()
    private let synth = AVSpeechSynthesizer()

    func say(_ text: String) {
        stop()
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
        try? session.setActive(true)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-IN") ?? AVSpeechSynthesisVoice(language: "en-GB")
        utterance.rate = 0.52
        synth.speak(utterance)
    }

    func stop() {
        if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
    }
}
