import SwiftUI
import UIKit

@main
struct LedgerApp: App {
    init() {
        // Transparent bars so the blueberry glow shows through; blueberry selection in the tab bar.
        let serif = { (size: CGFloat, weight: UIFont.Weight) -> UIFont in
            let base = UIFont.systemFont(ofSize: size, weight: weight)
            return UIFont(descriptor: base.fontDescriptor.withDesign(.serif) ?? base.fontDescriptor, size: size)
        }
        let nav = UINavigationBarAppearance()
        nav.configureWithTransparentBackground()
        nav.largeTitleTextAttributes = [.foregroundColor: UIColor(Theme.accentLight), .font: serif(34, .semibold)]
        nav.titleTextAttributes = [.foregroundColor: UIColor(Theme.text), .font: serif(17, .semibold)]
        UINavigationBar.appearance().standardAppearance = nav
        UINavigationBar.appearance().scrollEdgeAppearance = nav
        UINavigationBar.appearance().compactAppearance = nav

        let tab = UITabBarAppearance()
        tab.configureWithTransparentBackground()
        tab.backgroundColor = UIColor(Theme.ink).withAlphaComponent(0.92)
        tab.shadowColor = UIColor(Theme.accent).withAlphaComponent(0.15)
        for item in [tab.stackedLayoutAppearance, tab.inlineLayoutAppearance, tab.compactInlineLayoutAppearance] {
            item.normal.iconColor = UIColor(Theme.textFaint)
            item.normal.titleTextAttributes = [.foregroundColor: UIColor(Theme.textFaint)]
            item.selected.iconColor = UIColor(Theme.accentLight)
            item.selected.titleTextAttributes = [.foregroundColor: UIColor.white]
            item.normal.badgeBackgroundColor = UIColor(Theme.danger)
        }
        UITabBar.appearance().standardAppearance = tab
        UITabBar.appearance().scrollEdgeAppearance = tab
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .tint(Theme.accent)
                .preferredColorScheme(.dark)
        }
    }
}
