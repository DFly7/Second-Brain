import AVFoundation
import Foundation
import Observation
import Speech

enum RecordingState {
    case idle, recording, done
}

@Observable
@MainActor
final class VoiceRecorder: NSObject {
    private(set) var state: RecordingState = .idle
    private(set) var liveTranscript: String = ""
    var errorMessage: String?

    private let speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let audioEngine = AVAudioEngine()

    func startRecording() {
        guard state == .idle else { return }
        requestPermissions { [weak self] granted in
            guard let self, granted else {
                self?.errorMessage = "Microphone or speech recognition permission denied."
                return
            }
            self.beginRecording()
        }
    }

    func stopRecording() {
        guard state == .recording else { return }
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        state = .done
    }

    func discard() {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionRequest = nil
        recognitionTask = nil
        liveTranscript = ""
        state = .idle
    }

    // MARK: - Private

    private func requestPermissions(completion: @escaping (Bool) -> Void) {
        SFSpeechRecognizer.requestAuthorization { status in
            guard status == .authorized else { completion(false); return }
            AVAudioApplication.requestRecordPermission { granted in
                DispatchQueue.main.async { completion(granted) }
            }
        }
    }

    private func beginRecording() {
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
        guard let recognitionRequest else { return }
        recognitionRequest.shouldReportPartialResults = true

        let inputNode = audioEngine.inputNode
        let recordingFormat = inputNode.outputFormat(forBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: recordingFormat) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }

        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self else { return }
            if let result {
                self.liveTranscript = result.bestTranscription.formattedString
            }
            if error != nil || result?.isFinal == true {
                if self.state == .recording {
                    self.stopRecording()
                }
            }
        }

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            audioEngine.prepare()
            try audioEngine.start()
            state = .recording
            liveTranscript = ""
            errorMessage = nil
        } catch {
            errorMessage = "Failed to start recording: \(error.localizedDescription)"
            discard()
        }
    }
}
