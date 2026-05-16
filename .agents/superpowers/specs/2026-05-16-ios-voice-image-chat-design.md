# iOS Voice Ingest, Image Ingest & Chat — Design Spec

**Date:** 2026-05-16  
**Scope:** iOS client additions only. No backend changes required.

---

## Overview

Add three features to the existing `SecondBrainApp` iOS app:

1. **Voice ingest** — hold or tap to record, on-device live transcription via `SFSpeechRecognizer`, send transcribed text to `/ingest/text`
2. **Image ingest** — pick from photo library, capture with camera, or select from Files app, upload to `/ingest/file`
3. **Chat** — single-session message bubbles, new chat button, query the wiki via `/chat/message`

Navigation is a two-tab `TabView`: **Capture** (voice + image) and **Chat**.

---

## New Files

```
ios/SecondBrainApp/SecondBrainApp/
  Views/
    CaptureView.swift       ← voice recorder UI + image ingest buttons
    ChatView.swift          ← chat bubbles, input field, new session button
  Utilities/
    VoiceRecorder.swift     ← AVAudioSession + SFSpeechRecognizer state machine
```

**Modified files:**
- `Views/RootView.swift` — replace placeholder with `TabView` containing `CaptureView` and `ChatView`
- `Services/APIService.swift` — add `ingestText`, `ingestFile`, `sendMessage` methods + shared `performRequest` helper

---

## VoiceRecorder

`@Observable @MainActor final class VoiceRecorder`

### State machine

```
idle → recording → done
```

- `idle`: mic not active
- `recording`: audio engine running, partial transcription results streaming in
- `done`: recording stopped, final transcript available, ready to ingest

### Properties

| Property | Type | Description |
|---|---|---|
| `state` | `RecordingState` | Current state machine value |
| `liveTranscript` | `String` | Updates word-by-word during recording via partial results |
| `errorMessage` | `String?` | Permission denial or engine failure |

### Recording triggers

Two entry points, both call the same `startRecording()` / `stopRecording()` logic:

1. **Tap-to-toggle:** tapping the record button calls `startRecording()` when idle, `stopRecording()` when recording
2. **Hold-to-record (Snapchat-style):** `DragGesture(minimumDistance: 0)` on the button — `.onChanged` (first event, finger down) calls `startRecording()`, `.onEnded` (finger up) calls `stopRecording()`

### Live transcription

- `SFSpeechAudioBufferRecognitionRequest` with `shouldReportPartialResults = true`
- Partial results update `liveTranscript` on the main actor — view binds directly, no polling
- Streams only while screen is on and audio engine is active (automatic iOS behaviour)
- On `stopRecording()`: finalises the recognition request, last result becomes the confirmed transcript

### Permissions

- Requests `AVAudioSession` microphone permission and `SFSpeechRecognizer` speech recognition permission on first use
- Surfaces `errorMessage` if either is denied — `CaptureView` shows an alert

---

## CaptureView

### Layout

```
┌─────────────────────────────┐
│  Capture                    │
│                             │
│  ┌───────────────────────┐  │
│  │  Live transcript...   │  │  ← scrollable Text, word-by-word updates
│  │  (hidden when idle)   │  │
│  └───────────────────────┘  │
│                             │
│        [● Hold to Record]   │  ← hold OR tap-to-toggle
│        [✓ Ingest Note]      │  ← appears when state == .done
│                             │
│  ────────── or ──────────   │
│                             │
│   [📷 Camera] [🖼 Library]  │
│        [📁 Files]           │
│                             │
└─────────────────────────────┘
```

### Record button states

| State | Appearance |
|---|---|
| `idle` | Mic icon, label "Hold or tap to record" |
| `recording` | Red pulsing circle, label "Recording…" |
| `done` | Checkmark, label "Done" |

### Image ingest

Three buttons, each presents a sheet:
- **Camera** → `UIImagePickerController` (`sourceType: .camera`)
- **Library** → `PHPickerViewController` (single image, no editing)
- **Files** → `UIDocumentPickerViewController` (UTType: image types)

On selection: read image data, derive filename with correct extension (`.jpg`, `.png`, `.heic`→`.jpg`), call `apiService.ingestFile(data:filename:mimeType:)`. Show a brief success/error toast.

### Ingest Note button

Appears when `voiceRecorder.state == .done` and `liveTranscript` is non-empty. Calls `apiService.ingestText(text:title:)` with title `"Voice note"`. On success: reset recorder to idle, clear transcript, show toast.

---

## ChatView

### Layout

```
┌─────────────────────────────┐
│  Chat            [New Chat] │
│                             │
│  ┌───────────────────────┐  │
│  │  [Assistant bubble]   │  │
│  │       [User bubble]   │  │
│  │  [Assistant bubble]   │  │  ← ScrollViewReader scrolls to bottom on new message
│  │  [ProgressView]       │  │  ← shown while awaiting assistant response
│  └───────────────────────┘  │
│                             │
│  ┌─────────────────┐ [Send] │
└──┴─────────────────┴────────┘
```

### State

Held in `ChatView` directly (no separate view model needed at this scale):

| State | Type | Description |
|---|---|---|
| `messages` | `[ChatMessage]` | Local array, not persisted on device |
| `sessionId` | `String?` | Sent with each request; nil → backend creates new session |
| `inputText` | `String` | Bound to text field |
| `isLoading` | `Bool` | True while awaiting response |

`ChatMessage` is a local struct `{ id: UUID, role: "user"/"assistant", content: String }`.

### Send flow

1. Append user message to `messages` immediately (optimistic)
2. Clear `inputText`, set `isLoading = true`
3. Call `apiService.sendMessage(text:sessionId:)`
4. On success: store returned `sessionId`, append assistant message, set `isLoading = false`
5. On error: show inline error message below the input field

### New Chat

Tapping **New Chat** in the toolbar: set `sessionId = nil`, clear `messages`. Next send creates a fresh backend session.

### Mode

`mode` is hardcoded to `"query"`. Edit mode is out of scope.

---

## APIService additions

A private `performRequest<T: Decodable>(_ request: URLRequest) async throws -> T` helper is extracted to handle auth header injection, response status check, and JSON decoding — used by all three new methods and can replace the existing `health()` implementation.

### `ingestText(text: String, title: String) async throws`

```
POST /ingest/text
Content-Type: application/json
{ "text": "...", "title": "Voice note" }
```

Response: `{ "source_id": "...", "status": "converting" }` — caller ignores response body, shows success toast.

### `ingestFile(data: Data, filename: String, mimeType: String) async throws`

```
POST /ingest/file
Content-Type: multipart/form-data
file field: binary data with correct filename and MIME type
```

Filename extension is critical — backend uses it to route to Marker or text pipeline. HEIC images must be transcoded to JPEG before upload (using `UIImage` → `jpegData(compressionQuality: 0.9)`) since the backend doesn't handle HEIC.

### `sendMessage(text: String, sessionId: String?) async throws -> (answer: String, sessionId: String)`

```
POST /chat/message
Content-Type: application/json
{ "message": "...", "session_id": "..." | null, "mode": "query" }
```

Response: `{ "session_id": "...", "answer": "...", "cited_pages": [...] }` — returns `answer` and `session_id`, `cited_pages` ignored for now.

---

## Permissions (Info.plist additions)

| Key | Reason shown to user |
|---|---|
| `NSMicrophoneUsageDescription` | "Second Brain needs the microphone to record voice notes." |
| `NSSpeechRecognitionUsageDescription` | "Second Brain uses speech recognition to transcribe your voice notes." |
| `NSPhotoLibraryUsageDescription` | "Second Brain needs photo access to ingest images into your wiki." |
| `NSCameraUsageDescription` | "Second Brain uses the camera to capture images for your wiki." |

---

## Out of scope

- Chat SSE streaming (backend returns full response synchronously)
- Chat session history browser
- Edit mode chat
- Voice note playback
- Ingest progress tracking (no SSE client on iOS yet)
- Markdown viewer
