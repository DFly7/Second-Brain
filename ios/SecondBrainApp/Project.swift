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
            ]),
            sources: ["SecondBrainApp/**"],
            settings: .settings(
                configurations: [
                    .debug(name: "Debug", xcconfig: .relativeToManifest("Config-Debug.xcconfig")),
                    .release(name: "Release", xcconfig: .relativeToManifest("Config-Release.xcconfig")),
                ]
            )
        ),
    ]
)
