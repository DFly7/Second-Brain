import ProjectDescription

let project = Project(
    name: "SecondBrainApp",
    targets: [
        .target(
            name: "SecondBrainApp",
            destinations: .iOS,
            product: .app,
            bundleId: "com.darraghflynn.SecondBrainApp",
            deploymentTargets: .iOS("17.0"),
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
                "UILaunchScreen": [:],
            ]),
            sources: ["SecondBrainApp/**"],
            settings: .settings(
                base: [
                    // Signing: DEVELOPMENT_TEAM + CODE_SIGN_STYLE come from Config-*.xcconfig.
                    "DEVELOPMENT_TEAM": "$(DEVELOPMENT_TEAM)",
                    // Ensures xcodebuild exposes iOS Simulator destinations (not device-only).
                    "SUPPORTED_PLATFORMS": "iphoneos iphonesimulator",
                    // Tuist still emits SDKROOT=iphoneos; these make simulator SDK resolution explicit.
                    "SDKROOT[sdk=iphonesimulator*]": "iphonesimulator",
                    "SDKROOT[sdk=iphoneos*]": "iphoneos",
                ],
                configurations: [
                    .debug(name: "Debug", xcconfig: .relativeToManifest("Config-Debug.xcconfig")),
                    .release(name: "Release", xcconfig: .relativeToManifest("Config-Release.xcconfig")),
                ]
            )
        ),
    ]
)
