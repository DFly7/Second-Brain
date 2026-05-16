# iOS Voice Ingest, Image Ingest & Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add voice ingest (on-device transcription), image ingest (camera/library/Files), and a chat UI to the existing SecondBrainApp iOS app.

**Architecture:** Two-tab SwiftUI app (Capture + Chat). `VoiceRecorder` owns all mic/speech state. `APIService` gains three new methods via a shared `performRequest` helper. No backend changes required — all three features target existing endpoints.

**Tech Stack:** Swift 5.9, SwiftUI, `@Observable` (iOS 17+), `AVFoundation`, `Speech`, `PhotosUI`, `UIKit` (camera/Files pickers), Tuist project generation.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `ios/SecondBrainApp/Project.swift` | Modify | Add four `Info.plist` permission keys |
| `ios/SecondBrainApp/SecondBrainApp/Services/APIService.swift` | Modify | Add `performRequest` helper + `ingestText`, `ingestFile`, `sendMessage` |
| `ios/SecondBrainApp/SecondBrainApp/Utilities/VoiceRecorder.swift` | Create | `AVAudioSession` + `SFSpeechRecognizer` state machine, live transcript |
| `ios/SecondBrainApp/SecondBrainApp/Views/RootView.swift` | Modify | Replace `HomeView()` with `TabView` wrapping `CaptureView` + `ChatView` |
| `ios/SecondBrainApp/SecondBrainApp/Views/CaptureView.swift` | Create | Voice recorder UI + image ingest buttons |
| `ios/SecondBrainApp/SecondBrainApp/Views/ChatView.swift` | Create | Chat bubbles, input field, new session button |

---

## Task 1: Add permission keys to Project.swift

**Files:**
- Modify: `ios/SecondBrainApp/Project.swift`

All permission strings live in `Project.swift`'s `infoPlist` dict — Tuist writes them into the generated `.plist`. After editing, regenerate the Xcode project.

- [ ] **Step 1: Add the four permission strings**

Open `ios/SecondBrainApp/Project.swift`. Extend the `infoPlist: .extendingDefault(with: [...])` block — add after the existing `AUTHENTIK_REDIRECT_URI` entry:

```swift
"NSMicrophoneUsageDescription": "Second Brain needs the microphone to record voice notes.",
"NSSpeechRecognitionUsageDescription": "Second Brain uses speech recognition to transcribe your voice notes.",
"NSPhotoLibraryUsageDescription": "Second Brain needs photo access to ingest images into your wiki.",
"NSCameraUsageDescription": "Second Brain uses the camera to capture images for your wiki.",
```

The full `infoPlist` block should now be:

```swift
infoPlist: .extendingDefault(with: [
    "CFBundleURLTypes": [
        [
            "CFBundleURLSchemes": ["secondbrain"],
            "CFBundleURLName": "com.darraghflynn.SecondBrainApp",
        ],
    ],
    "BACKEND_URL": "$(BACKEND_URL)",
    "AUTHENTIK_AUTHORIZE_URL": "$(AUTHENTIK_AUTHORIZE_URL)",
    "AUTHENTIK_TOKEN_URL": "$(AUTHENTIK_TOKEN_URL)",
    "AUTHENTIK_CLIENT_ID": "$(AUTHENTIK_CLIENT_ID)",
    "AUTHENTIK_REDIRECT_URI": "$(AUTHENTIK_REDIRECT_URI)",
    "NSMicrophoneUsageDescription": "Second Brain needs the microphone to record voice notes.",
    "NSSpeechRecognitionUsageDescription": "Second Brain uses speech recognition to transcribe your voice notes.",
    "NSPhotoLibraryUsageDescription": "Second Brain needs photo access to ingest images into your wiki.",
    "NSCameraUsageDescription": "Second Brain uses the camera to capture images for your wiki.",
]),
```

- [ ] **Step 2: Regenerate the Xcode project**

```bash
cd ios/SecondBrainApp && tuist generate
```

Expected: `SecondBrainApp.xcworkspace` regenerated, no errors.

- [ ] **Step 3: Commit**

```bash
git add ios/SecondBrainApp/Project.swift
git commit -m "feat(ios): add mic, speech, photo, camera permission strings"
```

---

## Task 2: Expand APIService — performRequest helper + ingestText

**Files:**
- Modify: `ios/SecondBrainApp/SecondBrainApp/Services/APIService.swift`

The current `health()` method manually builds requests. Extract that pattern into a private `performRequest` helper first, then build `ingestText` on top of it.

- [ ] **Step 1: Replace APIService.swift with the expanded version**

```swift
import Foundation
import Observation

@Observable
@MainActor
final class APIService {
    private let authService: AuthService

    init(authService: AuthService) {
        self.authService = authService
    }

    // MARK: - Existing

    func health() async throws -> String {
        let url = URL(string: APIConfig.shared.backendURL + "/health")!
        let data: [String: String] = try await performRequest(url: url, method: "GET")
        return data["status"] ?? "unknown"
    }

    // MARK: - Ingest

    func ingestText(text: String, title: String) async throws {
        let url = URL(string: APIConfig.shared.backendURL + "/ingest/text")!
        let body = try JSONEncoder().encode(["text": text, "title": title])
        let _: IngestResponse = try await performRequest(url: url, method: "POST", body: body, contentType: "application/json")
    }

    func ingestFile(data: Data, filename: String, mimeType: String) async throws {
        let url = URL(string: APIConfig.shared.backendURL + "/ingest/file")!
        let boundary = "Boundary-\(UUID().uuidString)"
        let body = multipartBody(data: data, filename: filename, mimeType: mimeType, boundary: boundary)
        let _: IngestResponse = try await performRequest(
            url: url,
            method: "POST",
            body: body,
            contentType: "multipart/form-data; boundary=\(boundary)"
        )
    }

    // MARK: - Chat

    func sendMessage(text: String, sessionId: String?) async throws -> (answer: String, sessionId: String) {
        let url = URL(string: APIConfig.shared.backendURL + "/chat/message")!
        var payload: [String: String?] = ["message": text, "mode": "query"]
        payload["session_id"] = sessionId
        let body = try JSONEncoder().encode(payload)
        let response: ChatMessageResponse = try await performRequest(url: url, method: "POST", body: body, contentType: "application/json")
        return (response.answer, response.sessionId)
    }

    // MARK: - Private helpers

    private func performRequest<T: Decodable>(
        url: URL,
        method: String,
        body: Data? = nil,
        contentType: String? = nil
    ) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30
        if let token = authService.accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.httpBody = body
            request.setValue(contentType ?? "application/octet-stream", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw APIError.requestFailed(statusCode: code)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func multipartBody(data: Data, filename: String, mimeType: String, boundary: String) -> Data {
        var body = Data()
        let crlf = "\r\n"
        body.append("--\(boundary)\(crlf)".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\(crlf)".data(using: .utf8)!)
        body.append("Content-Type: \(mimeType)\(crlf)\(crlf)".data(using: .utf8)!)
        body.append(data)
        body.append("\(crlf)--\(boundary)--\(crlf)".data(using: .utf8)!)
        return body
    }
}

// MARK: - Response types

private struct IngestResponse: Decodable {
    let sourceId: String
    let status: String
    enum CodingKeys: String, CodingKey {
        case sourceId = "source_id"
        case status
    }
}

private struct ChatMessageResponse: Decodable {
    let answer: String
    let sessionId: String
    enum CodingKeys: String, CodingKey {
        case answer
        case sessionId = "session_id"
    }
}

enum APIError: LocalizedError {
    case requestFailed(statusCode: Int)

    var errorDescription: String? {
        switch self {
        case .requestFailed(let code): "Request failed (HTTP \(code))"
        }
    }
}
```

- [ ] **Step 2: Build to verify no compile errors**

Open `ios/SecondBrainApp/SecondBrainApp.xcworkspace` in Xcode and press `Cmd+B`, or run:

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|warning:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 3: Commit**

```bash
git add ios/SecondBrainApp/SecondBrainApp/Services/APIService.swift
git commit -m "feat(ios): add performRequest helper, ingestText, ingestFile, sendMessage"
```

---

## Task 3: Implement VoiceRecorder

**Files:**
- Create: `ios/SecondBrainApp/SecondBrainApp/Utilities/VoiceRecorder.swift`

`VoiceRecorder` owns all microphone and speech state. The view only binds to its published properties — no AVFoundation in any view.

`SFSpeechAudioBufferRecognitionRequest` with `shouldReportPartialResults = true` fires a result callback every few words. Each callback updates `liveTranscript`, which the view binds to for real-time display.

- [ ] **Step 1: Create VoiceRecorder.swift**

```swift
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
```

- [ ] **Step 2: Build to verify no compile errors**

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 3: Commit**

```bash
git add ios/SecondBrainApp/SecondBrainApp/Utilities/VoiceRecorder.swift
git commit -m "feat(ios): add VoiceRecorder with live transcription and hold-to-record support"
```

---

## Task 4: Update RootView to TabView

**Files:**
- Modify: `ios/SecondBrainApp/SecondBrainApp/Views/RootView.swift`

Replace `HomeView()` with a `TabView` containing stub views. `CaptureView` and `ChatView` don't exist yet — create minimal stubs so the project compiles before Tasks 5 and 6 flesh them out.

- [ ] **Step 1: Replace RootView.swift**

```swift
import SwiftUI

struct RootView: View {
    @Environment(AuthService.self) private var authService

    var body: some View {
        if authService.isAuthenticated {
            TabView {
                CaptureView()
                    .tabItem { Label("Capture", systemImage: "mic.fill") }
                ChatView()
                    .tabItem { Label("Chat", systemImage: "bubble.left.and.bubble.right.fill") }
            }
        } else {
            AuthView()
        }
    }
}
```

- [ ] **Step 2: Create CaptureView stub**

Create `ios/SecondBrainApp/SecondBrainApp/Views/CaptureView.swift`:

```swift
import SwiftUI

struct CaptureView: View {
    var body: some View {
        Text("Capture")
    }
}
```

- [ ] **Step 3: Create ChatView stub**

Create `ios/SecondBrainApp/SecondBrainApp/Views/ChatView.swift`:

```swift
import SwiftUI

struct ChatView: View {
    var body: some View {
        Text("Chat")
    }
}
```

- [ ] **Step 4: Build to verify tab bar compiles**

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 5: Commit**

```bash
git add ios/SecondBrainApp/SecondBrainApp/Views/RootView.swift \
        ios/SecondBrainApp/SecondBrainApp/Views/CaptureView.swift \
        ios/SecondBrainApp/SecondBrainApp/Views/ChatView.swift
git commit -m "feat(ios): wire up tab bar with Capture and Chat tabs"
```

---

## Task 5: Implement CaptureView

**Files:**
- Modify: `ios/SecondBrainApp/SecondBrainApp/Views/CaptureView.swift`

Replace the stub. `VoiceRecorder` is injected as `@State` owned by `CaptureView`. Image picker sheets are presented via boolean state flags. HEIC images are transcoded to JPEG inside this view before calling `apiService.ingestFile`.

`DragGesture(minimumDistance: 0)` on the record button handles hold-to-record: `.onChanged` fires on touch-down (triggers `startRecording()` once via a flag), `.onEnded` fires on release (triggers `stopRecording()`).

- [ ] **Step 1: Replace CaptureView.swift**

```swift
import AVFoundation
import PhotosUI
import Speech
import SwiftUI
import UIKit
import UniformTypeIdentifiers

struct CaptureView: View {
    @Environment(APIService.self) private var apiService
    @State private var recorder = VoiceRecorder()

    // Gesture state for hold-to-record vs tap-to-toggle
    @GestureState private var isButtonPressed = false
    @State private var buttonPressDate: Date?
    @State private var recordStartedThisGesture = false

    @State private var showCamera = false
    @State private var showLibrary = false
    @State private var showFiles = false

    @State private var toast: String?
    @State private var isIngesting = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 28) {
                    transcriptSection
                    recordButton
                    if recorder.state == .done {
                        actionButtons
                    }
                    Divider().padding(.horizontal)
                    imageButtons
                }
                .padding(24)
            }
            .navigationTitle("Capture")
            .sheet(isPresented: $showCamera) {
                CameraPickerView { image in
                    ingestUIImage(image, source: "camera")
                }
            }
            .sheet(isPresented: $showLibrary) {
                LibraryPickerView { image in
                    ingestUIImage(image, source: "library")
                }
            }
            .sheet(isPresented: $showFiles) {
                FilesPickerView { data, filename in
                    Task { await ingestFileData(data, filename: filename, mimeType: mimeType(for: filename)) }
                }
            }
            .overlay(alignment: .top) {
                if let toast {
                    Text(toast)
                        .font(.footnote)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(.thinMaterial, in: Capsule())
                        .padding(.top, 8)
                        .transition(.move(edge: .top).combined(with: .opacity))
                }
            }
            .alert("Permission Error", isPresented: Binding(
                get: { recorder.errorMessage != nil },
                set: { if !$0 { recorder.errorMessage = nil } }
            )) {
                Button("OK", role: .cancel) { recorder.errorMessage = nil }
            } message: {
                Text(recorder.errorMessage ?? "")
            }
        }
    }

    // MARK: - Subviews

    private var transcriptSection: some View {
        Group {
            if !recorder.liveTranscript.isEmpty {
                ScrollView {
                    Text(recorder.liveTranscript)
                        .font(.body)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
                .frame(maxHeight: 200)
                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    // The record button uses a time-threshold to distinguish tap-to-toggle from hold-to-record:
    //   Quick touch (<0.3s): tap mode — touch-down starts recording, touch-up leaves it running;
    //                        a second tap stops it.
    //   Sustained touch (≥0.3s): hold mode — touch-down starts recording, touch-up stops it.
    // @GestureState resets to false automatically when the gesture ends, so `isButtonPressed`
    // drives the onChange that fires on press-down.
    private var recordButton: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(recorder.state == .recording ? Color.red : Color.accentColor)
                    .frame(width: 80, height: 80)
                    .scaleEffect(recorder.state == .recording ? 1.15 : 1.0)
                    .animation(
                        recorder.state == .recording
                            ? .easeInOut(duration: 0.6).repeatForever(autoreverses: true)
                            : .default,
                        value: recorder.state == .recording
                    )
                Image(systemName: recorder.state == .done ? "checkmark" : "mic.fill")
                    .font(.system(size: 32))
                    .foregroundStyle(.white)
            }
            .gesture(
                DragGesture(minimumDistance: 0)
                    .updating($isButtonPressed) { _, state, _ in state = true }
                    .onEnded { _ in
                        let pressDuration = buttonPressDate.map { -$0.timeIntervalSinceNow } ?? 0
                        buttonPressDate = nil
                        defer { recordStartedThisGesture = false }
                        guard recorder.state == .recording else { return }
                        if !recordStartedThisGesture {
                            // Was already recording before this gesture: tap-to-stop
                            recorder.stopRecording()
                        } else if pressDuration >= 0.3 {
                            // Started recording this gesture + held long enough: hold-to-record release
                            recorder.stopRecording()
                        }
                        // else: started recording + quick tap → recording continues until next tap
                    }
            )
            .onChange(of: isButtonPressed) { _, pressed in
                guard pressed else { return }
                buttonPressDate = Date()
                if recorder.state == .idle {
                    recorder.startRecording()
                    recordStartedThisGesture = true
                } else {
                    recordStartedThisGesture = false
                }
            }

            Text(recordButtonLabel)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var recordButtonLabel: String {
        switch recorder.state {
        case .idle: "Hold or tap to record"
        case .recording: "Recording…"
        case .done: "Done"
        }
    }

    private var actionButtons: some View {
        HStack(spacing: 16) {
            Button(role: .destructive) {
                recorder.discard()
            } label: {
                Label("Discard", systemImage: "trash")
            }
            .buttonStyle(.bordered)

            Button {
                Task { await ingestVoiceNote() }
            } label: {
                if isIngesting {
                    ProgressView().controlSize(.small)
                } else {
                    Label("Ingest Note", systemImage: "arrow.up.circle.fill")
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isIngesting || recorder.liveTranscript.isEmpty)
        }
    }

    private var imageButtons: some View {
        VStack(spacing: 12) {
            Text("Ingest Image")
                .font(.headline)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: 12) {
                Button { showCamera = true } label: {
                    Label("Camera", systemImage: "camera.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(!UIImagePickerController.isSourceTypeAvailable(.camera))

                Button { showLibrary = true } label: {
                    Label("Library", systemImage: "photo.fill")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }

            Button { showFiles = true } label: {
                Label("Files", systemImage: "folder.fill")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
        }
    }

    // MARK: - Actions

    private func ingestVoiceNote() async {
        isIngesting = true
        do {
            try await apiService.ingestText(text: recorder.liveTranscript, title: "Voice note")
            recorder.discard()
            showToast("Voice note ingested")
        } catch {
            showToast("Failed: \(error.localizedDescription)")
        }
        isIngesting = false
    }

    private func ingestUIImage(_ image: UIImage, source: String) {
        guard let jpeg = image.jpegData(compressionQuality: 0.9) else { return }
        Task { await ingestFileData(jpeg, filename: "image-\(source).jpg", mimeType: "image/jpeg") }
    }

    private func ingestFileData(_ data: Data, filename: String, mimeType: String) async {
        do {
            try await apiService.ingestFile(data: data, filename: filename, mimeType: mimeType)
            showToast("Image ingested")
        } catch {
            showToast("Failed: \(error.localizedDescription)")
        }
    }

    private func mimeType(for filename: String) -> String {
        let ext = filename.split(separator: ".").last?.lowercased() ?? ""
        switch ext {
        case "jpg", "jpeg": return "image/jpeg"
        case "png": return "image/png"
        case "webp": return "image/webp"
        default: return "application/octet-stream"
        }
    }

    private func showToast(_ message: String) {
        withAnimation { toast = message }
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
            withAnimation { toast = nil }
        }
    }
}
```

- [ ] **Step 2: Create CameraPickerView helper**

Append to `CaptureView.swift` (same file, after the closing brace of `CaptureView`):

```swift
// MARK: - Picker wrappers

private struct CameraPickerView: UIViewControllerRepresentable {
    let onCapture: (UIImage) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onCapture: onCapture) }

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onCapture: (UIImage) -> Void
        init(onCapture: @escaping (UIImage) -> Void) { self.onCapture = onCapture }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage { onCapture(image) }
            picker.dismiss(animated: true)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
        }
    }
}

private struct LibraryPickerView: UIViewControllerRepresentable {
    let onPick: (UIImage) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration()
        config.filter = .images
        config.selectionLimit = 1
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: PHPickerViewController, context: Context) {}

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPick: (UIImage) -> Void
        init(onPick: @escaping (UIImage) -> Void) { self.onPick = onPick }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            guard let provider = results.first?.itemProvider, provider.canLoadObject(ofClass: UIImage.self) else { return }
            provider.loadObject(ofClass: UIImage.self) { object, _ in
                guard let image = object as? UIImage else { return }
                DispatchQueue.main.async { self.onPick(image) }
            }
        }
    }
}

private struct FilesPickerView: UIViewControllerRepresentable {
    let onPick: (Data, String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let types: [UTType] = [.jpeg, .png, .webP, .image]
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: types)
        picker.delegate = context.coordinator
        picker.allowsMultipleSelection = false
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (Data, String) -> Void
        init(onPick: @escaping (Data, String) -> Void) { self.onPick = onPick }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first,
                  url.startAccessingSecurityScopedResource(),
                  let data = try? Data(contentsOf: url) else { return }
            url.stopAccessingSecurityScopedResource()
            DispatchQueue.main.async { self.onPick(data, url.lastPathComponent) }
        }
    }
}
```

- [ ] **Step 3: Build to verify**

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 4: Manual smoke test in simulator**

Run in simulator. On the Capture tab:
- Tap the mic button → it should show a permission dialog on first run
- Hold the button → recording starts (red pulse), release → state moves to done, transcript visible
- Tap Discard → transcript clears, button returns to idle
- Record again, tap Ingest Note → toast "Voice note ingested" (or auth error if not connected to backend — that's fine)

- [ ] **Step 5: Commit**

```bash
git add ios/SecondBrainApp/SecondBrainApp/Views/CaptureView.swift
git commit -m "feat(ios): implement CaptureView with voice ingest and image ingest"
```

---

## Task 6: Implement ChatView

**Files:**
- Modify: `ios/SecondBrainApp/SecondBrainApp/Views/ChatView.swift`

Replace the stub. All state lives directly in the view — no separate view model. `ScrollViewReader` auto-scrolls to the newest message. `sessionId` persists across messages in the same conversation; "New Chat" clears it.

- [ ] **Step 1: Replace ChatView.swift**

```swift
import SwiftUI

struct ChatView: View {
    @Environment(APIService.self) private var apiService

    @State private var messages: [ChatMessage] = []
    @State private var sessionId: String?
    @State private var inputText: String = ""
    @State private var isLoading: Bool = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                messageList
                Divider()
                inputBar
            }
            .navigationTitle("Chat")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("New Chat") {
                        messages = []
                        sessionId = nil
                        errorMessage = nil
                    }
                    .disabled(messages.isEmpty)
                }
            }
        }
    }

    // MARK: - Subviews

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 12) {
                    ForEach(messages) { message in
                        MessageBubble(message: message)
                    }
                    if isLoading {
                        HStack {
                            ProgressView()
                                .padding(12)
                                .background(Color(.secondarySystemBackground), in: RoundedRectangle(cornerRadius: 16))
                            Spacer()
                        }
                        .padding(.horizontal, 16)
                        .id("loading")
                    }
                    if let error = errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding(.horizontal, 16)
                    }
                }
                .padding(.vertical, 12)
            }
            .onChange(of: messages.count) {
                withAnimation { proxy.scrollTo(messages.last?.id ?? "loading", anchor: .bottom) }
            }
            .onChange(of: isLoading) {
                if isLoading { withAnimation { proxy.scrollTo("loading", anchor: .bottom) } }
            }
        }
    }

    private var inputBar: some View {
        HStack(spacing: 8) {
            TextField("Ask your wiki…", text: $inputText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)
                .onSubmit { Task { await send() } }

            Button {
                Task { await send() }
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 32))
            }
            .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty || isLoading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }

    // MARK: - Actions

    private func send() async {
        let text = inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }

        inputText = ""
        errorMessage = nil
        messages.append(ChatMessage(role: .user, content: text))
        isLoading = true

        do {
            let (answer, newSessionId) = try await apiService.sendMessage(text: text, sessionId: sessionId)
            sessionId = newSessionId
            messages.append(ChatMessage(role: .assistant, content: answer))
        } catch {
            errorMessage = error.localizedDescription
        }

        isLoading = false
    }
}

// MARK: - Supporting types

private struct ChatMessage: Identifiable {
    let id = UUID()
    let role: Role
    let content: String

    enum Role { case user, assistant }
}

private struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack {
            if message.role == .user { Spacer(minLength: 60) }
            Text(message.content)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(
                    message.role == .user ? Color.accentColor : Color(.secondarySystemBackground),
                    in: RoundedRectangle(cornerRadius: 18)
                )
                .foregroundStyle(message.role == .user ? .white : .primary)
            if message.role == .assistant { Spacer(minLength: 60) }
        }
        .padding(.horizontal, 16)
    }
}
```

- [ ] **Step 2: Build to verify**

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 3: Manual smoke test in simulator**

Run in simulator, switch to Chat tab:
- Type a message and tap Send → user bubble appears immediately, loading spinner shows
- If connected to backend: assistant bubble appears with the answer
- "New Chat" button becomes enabled after first message; tapping it clears all bubbles

- [ ] **Step 4: Commit**

```bash
git add ios/SecondBrainApp/SecondBrainApp/Views/ChatView.swift
git commit -m "feat(ios): implement ChatView with message bubbles and session management"
```

---

## Task 7: Remove HomeView

**Files:**
- Delete: `ios/SecondBrainApp/SecondBrainApp/Views/HomeView.swift`

`HomeView` is replaced by the tab bar. It's dead code.

- [ ] **Step 1: Delete HomeView.swift**

```bash
rm ios/SecondBrainApp/SecondBrainApp/Views/HomeView.swift
```

- [ ] **Step 2: Build to verify nothing references it**

```bash
cd ios/SecondBrainApp
xcodebuild -workspace SecondBrainApp.xcworkspace -scheme SecondBrainApp -destination 'platform=iOS Simulator,name=iPhone 16' build 2>&1 | grep -E "error:|BUILD"
```

Expected: `BUILD SUCCEEDED`

- [ ] **Step 3: Commit**

```bash
git add -u ios/SecondBrainApp/SecondBrainApp/Views/HomeView.swift
git commit -m "chore(ios): remove HomeView, replaced by CaptureView + ChatView tab bar"
```

---

## Task 8: End-to-end verification

A checklist to confirm the full flow works against the real backend (Pi or local Docker stack).

- [ ] **Voice ingest**
  - Open app → Capture tab
  - Hold mic button → speak a sentence → release
  - Transcript appears word-by-word in the scroll area
  - Tap Ingest Note → toast "Voice note ingested"
  - Open web app → confirm note appears in wiki sources

- [ ] **Voice discard**
  - Record a note → tap Discard
  - Transcript clears, button returns to idle, nothing ingested

- [ ] **Image ingest (library)**
  - Tap Library → pick a photo → toast "Image ingested"
  - Open web app → confirm image source appears

- [ ] **Image ingest (camera)**
  - Tap Camera → take photo → toast "Image ingested"
  - (Simulator: camera not available — test on device)

- [ ] **Image ingest (Files)**
  - Tap Files → pick a JPEG from Files app → toast "Image ingested"

- [ ] **Chat**
  - Switch to Chat tab → type a question about something in the wiki → Send
  - Assistant bubble appears with answer
  - Tap New Chat → bubbles clear, next message starts a fresh session
