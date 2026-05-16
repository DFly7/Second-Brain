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
