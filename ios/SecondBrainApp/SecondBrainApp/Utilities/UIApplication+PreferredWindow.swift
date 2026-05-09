import UIKit

extension UIApplication {
    /// Picks a window for presentation: foreground-active scenes first, then others;
    /// within each scene prefers the key window, then the first window.
    @MainActor
    static func preferredPresentationWindow() -> UIWindow? {
        let scenes = shared.connectedScenes.compactMap { $0 as? UIWindowScene }

        func window(in scene: UIWindowScene) -> UIWindow? {
            scene.windows.first(where: \.isKeyWindow) ?? scene.windows.first
        }

        for scene in scenes where scene.activationState == .foregroundActive {
            if let w = window(in: scene) { return w }
        }
        for scene in scenes where scene.activationState != .foregroundActive {
            if let w = window(in: scene) { return w }
        }
        return nil
    }
}
