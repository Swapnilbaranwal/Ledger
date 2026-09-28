import SwiftUI

// MARK: - Theme: blueberry and white, with glow

/// One palette for the whole app. Dark by design: blueberry light over midnight, white for emphasis.
enum Theme {
    // Surfaces
    static let ink = Color(hex: 0x07081A)          // midnight page
    static let raised = Color(hex: 0x12143A)       // cards
    static let raisedHigh = Color(hex: 0x1B1E4D)   // inputs, pressed cards
    static let hairline = Color.white.opacity(0.10)

    // Blueberry
    static let accent = Color(hex: 0x6B72FF)       // blueberry
    static let accentLight = Color(hex: 0xA9AEFF)  // blueberry milk
    static let accentDeep = Color(hex: 0x3B32B8)   // ripe blueberry
    static let depth = Color(hex: 0x2A2580)        // top-of-page wash
    static let onAccent = Color.white

    // Text
    static let text = Color.white
    static let textDim = Color(hex: 0xBFC2EE)
    static let textFaint = Color(hex: 0x7E82B8)

    // Status, tuned to sit on blueberry
    static let success = Color(hex: 0x6EE7B7)
    static let danger = Color(hex: 0xFF7A8A)
    static let warning = Color(hex: 0xFFC46B)
    static let info = Color(hex: 0x7CC4FF)

    /// Buttons, active states: juicy blueberry.
    static let accentGradient = LinearGradient(colors: [Color(hex: 0x8C8FFF), accent, accentDeep],
                                               startPoint: .topLeading, endPoint: .bottomTrailing)
    /// White emphasis (selected pills, primary buttons): pearl white with a cool edge.
    static let pearl = LinearGradient(colors: [.white, Color(hex: 0xE4E6FF)], startPoint: .top, endPoint: .bottom)

    // MARK: Fonts (both ship with iOS: nothing to bundle)

    /// Didot: high-contrast display serif for titles and money.
    static func display(_ size: CGFloat, _ weight: Font.Weight = .semibold) -> Font {
        .custom(weight == .regular ? "Didot" : "Didot-Bold", size: size, relativeTo: .title)
    }

    /// Avenir Next: geometric sans for everything else.
    static func sans(_ size: CGFloat, _ weight: Font.Weight = .regular, relativeTo style: Font.TextStyle = .body) -> Font {
        let name: String
        switch weight {
        case .ultraLight, .thin, .light: name = "AvenirNext-UltraLight"
        case .medium: name = "AvenirNext-Medium"
        case .semibold: name = "AvenirNext-DemiBold"
        case .bold, .heavy, .black: name = "AvenirNext-Bold"
        default: name = "AvenirNext-Regular"
        }
        return .custom(name, size: size, relativeTo: style)
    }
}

extension Color {
    init(hex: UInt32, opacity: Double = 1) {
        self.init(.sRGB, red: Double((hex >> 16) & 0xFF) / 255, green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255, opacity: opacity)
    }
}

// MARK: - Glow

/// Page background: midnight with slowly drifting blueberry light.
struct AmbientBackground: View {
    @State private var drift = false

    var body: some View {
        ZStack {
            Theme.ink
            LinearGradient(colors: [Theme.depth.opacity(0.95), Color(hex: 0x14124A).opacity(0.6), Theme.ink],
                           startPoint: .top, endPoint: .init(x: 0.5, y: 0.6))
            glow(Theme.accent, size: 360, x: drift ? -110 : -60, y: drift ? -300 : -250, opacity: 0.55)
            glow(Color(hex: 0x9B6BFF), size: 280, x: drift ? 150 : 110, y: drift ? -140 : -200, opacity: 0.35)
            glow(Theme.info, size: 300, x: drift ? 90 : 140, y: drift ? 380 : 330, opacity: 0.16)
        }
        .ignoresSafeArea()
        .onAppear {
            withAnimation(.easeInOut(duration: 9).repeatForever(autoreverses: true)) { drift = true }
        }
    }

    private func glow(_ color: Color, size: CGFloat, x: CGFloat, y: CGFloat, opacity: Double) -> some View {
        Circle()
            .fill(color.opacity(opacity))
            .frame(width: size, height: size)
            .blur(radius: 90)
            .offset(x: x, y: y)
    }
}

/// Raised glass card with a white hairline; `accent` adds a coloured rim and halo.
struct LedgerCard: ViewModifier {
    var accent: Color? = nil
    var radius: CGFloat = 18

    func body(content: Content) -> some View {
        let shape = RoundedRectangle(cornerRadius: radius, style: .continuous)
        content
            .background {
                shape.fill(Theme.raised.opacity(0.72))
                    .background(.ultraThinMaterial.opacity(0.35), in: shape)
            }
            .overlay {
                shape.strokeBorder(
                    LinearGradient(colors: [(accent ?? .white).opacity(accent == nil ? 0.16 : 0.6),
                                            (accent ?? .white).opacity(0.04)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: accent == nil ? 0.7 : 1)
            }
            .shadow(color: (accent ?? Theme.accent).opacity(accent == nil ? 0.10 : 0.30), radius: 16, y: 6)
    }
}

extension View {
    func ledgerCard(accent: Color? = nil, radius: CGFloat = 18) -> some View {
        modifier(LedgerCard(accent: accent, radius: radius))
    }

    func ledgerBackground() -> some View {
        background(AmbientBackground())
    }

    /// Soft coloured halo behind a shape or glyph.
    func glow(_ color: Color, radius: CGFloat = 12, strength: Double = 0.7) -> some View {
        shadow(color: color.opacity(strength), radius: radius)
            .shadow(color: color.opacity(strength * 0.4), radius: radius * 2.2)
    }
}

/// Primary action: pearl-white capsule, blueberry label, blueberry glow.
struct PrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sans(16, .semibold))
            .padding(.vertical, 13)
            .frame(maxWidth: .infinity)
            .foregroundStyle(Theme.accentDeep)
            .background(Capsule().fill(Theme.pearl))
            .glow(Theme.accent, radius: 10, strength: configuration.isPressed ? 0.3 : 0.6)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(.snappy(duration: 0.15), value: configuration.isPressed)
    }
}

// MARK: - Services

/// Colour + SF Symbol per integration.
enum ServiceStyle {
    static func icon(_ service: String?) -> String {
        switch service {
        case "paypal": return "creditcard.fill"
        case "notion": return "doc.text.fill"
        case "gmail":  return "envelope.fill"
        case "jira":   return "ticket.fill"
        case "slack":  return "number"
        default:       return "sparkles"
        }
    }

    static func color(_ service: String?) -> Color {
        switch service {
        case "paypal": return Color(hex: 0x5AA9FF)
        case "notion": return Color(hex: 0xE8E9F7)
        case "gmail":  return Color(hex: 0xFF7A6B)
        case "jira":   return Color(hex: 0x6F8BFF)
        case "slack":  return Color(hex: 0xD47BFF)
        default:       return Theme.accent
        }
    }

    /// Two-stop gradient for the miniature app icon.
    static func gradient(_ service: String?) -> [Color] {
        switch service {
        case "paypal": return [Color(hex: 0x6FC3FF), Color(hex: 0x1F5FD6)]
        case "notion": return [Color(hex: 0xFFFFFF), Color(hex: 0xB9BCD9)]
        case "gmail":  return [Color(hex: 0xFF9A7A), Color(hex: 0xD93A4A)]
        case "jira":   return [Color(hex: 0x8FA6FF), Color(hex: 0x2F4BD1)]
        case "slack":  return [Color(hex: 0xE59BFF), Color(hex: 0x7A2FCF)]
        default:       return [Color(hex: 0x8C8FFF), Theme.accentDeep]
        }
    }

    static func name(_ service: String?) -> String {
        switch service {
        case "paypal": return "PayPal"
        case "notion": return "Notion"
        case "gmail":  return "Gmail"
        case "jira":   return "Jira"
        case "slack":  return "Slack"
        default:       return "Agent"
        }
    }
}

/// Miniature glossy app icon for a service: gradient tile, white glyph, top gloss, glow.
struct ServiceGlyph: View {
    let service: String?
    var size: CGFloat = 32
    var lit: Bool = true

    var body: some View {
        let colors = ServiceStyle.gradient(service)
        let shape = RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
        ZStack {
            shape.fill(LinearGradient(colors: colors, startPoint: .topLeading, endPoint: .bottomTrailing))
            shape.fill(LinearGradient(colors: [.white.opacity(0.45), .clear], startPoint: .top, endPoint: .center))
                .padding(size * 0.06)
                .mask(shape)
            Image(systemName: ServiceStyle.icon(service))
                .font(.system(size: size * 0.46, weight: .bold))
                .foregroundStyle(service == "notion" ? Color(hex: 0x1B1E4D) : .white)
                .shadow(color: .black.opacity(0.25), radius: 1, y: 1)
        }
        .frame(width: size, height: size)
        .overlay(shape.strokeBorder(.white.opacity(0.35), lineWidth: 0.6))
        .saturation(lit ? 1 : 0.45)
        .opacity(lit ? 1 : 0.7)
        .glow(colors.last ?? Theme.accent, radius: lit ? size * 0.3 : 0, strength: lit ? 0.6 : 0)
    }
}

struct ServiceBadge: View {
    let service: String
    var active: Bool = true

    var body: some View {
        HStack(spacing: 7) {
            ServiceGlyph(service: service, size: 20, lit: active)
            Text(ServiceStyle.name(service))
                .font(Theme.sans(13, .semibold))
                .foregroundStyle(active ? Theme.text : Theme.textFaint)
        }
        .padding(.leading, 5)
        .padding(.trailing, 11)
        .padding(.vertical, 5)
        .background(Capsule().fill(active ? Theme.raisedHigh : Theme.raised.opacity(0.7)))
        .overlay(Capsule().strokeBorder(active ? ServiceStyle.color(service).opacity(0.55) : Theme.hairline,
                                        lineWidth: active ? 1 : 0.6))
        .glow(ServiceStyle.color(service), radius: 8, strength: active ? 0.45 : 0)
    }
}

// MARK: - Miniatures

/// Home-screen miniature: floating glass cards (a receipt, a case note, a shield) and coins,
/// a tiny diorama of what Ledger does. Floats gently.
struct HeroMiniature: View {
    @State private var float = false

    var body: some View {
        ZStack {
            Circle()
                .fill(Theme.accent.opacity(0.45))
                .frame(width: 170, height: 170)
                .blur(radius: 50)

            // Back: a case note
            miniCard(width: 118, height: 142) {
                VStack(alignment: .leading, spacing: 7) {
                    ServiceGlyph(service: "notion", size: 18)
                    ForEach(0..<5, id: \.self) { i in
                        Capsule().fill(.white.opacity(i == 0 ? 0.55 : 0.2))
                            .frame(width: i == 0 ? 70 : CGFloat([84, 62, 78, 50][i - 1]), height: 5)
                    }
                }
                .padding(12)
            }
            .rotationEffect(.degrees(-12))
            .offset(x: -64, y: float ? -4 : 4)

            // Middle: the receipt with the money
            miniCard(width: 132, height: 150) {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        ServiceGlyph(service: "paypal", size: 18)
                        Spacer()
                        Text("WON")
                            .font(Theme.sans(8, .bold))
                            .foregroundStyle(Theme.success)
                            .padding(.horizontal, 5).padding(.vertical, 2)
                            .background(Theme.success.opacity(0.15), in: Capsule())
                    }
                    Text("$420")
                        .font(Theme.display(28))
                        .foregroundStyle(.white)
                    Capsule().fill(.white.opacity(0.22)).frame(width: 76, height: 5)
                    Capsule().fill(.white.opacity(0.14)).frame(width: 58, height: 5)
                    Spacer(minLength: 0)
                    HStack(spacing: 4) {
                        Image(systemName: "checkmark.seal.fill").foregroundStyle(Theme.success)
                        Text("Evidence sent").foregroundStyle(Theme.textDim)
                    }
                    .font(Theme.sans(9, .semibold))
                }
                .padding(12)
            }
            .rotationEffect(.degrees(4))
            .offset(x: 10, y: float ? 6 : -6)

            // Front: shield
            ZStack {
                Circle().fill(Theme.pearl).frame(width: 58, height: 58)
                Image(systemName: "checkmark.shield.fill")
                    .font(.system(size: 26, weight: .bold))
                    .foregroundStyle(Theme.accentGradient)
            }
            .glow(Theme.accent, radius: 14, strength: 0.8)
            .offset(x: 84, y: float ? 42 : 34)

            coin.offset(x: -92, y: float ? 70 : 62)
            coin.scaleEffect(0.7).offset(x: 96, y: float ? -62 : -54)
        }
        .frame(height: 190)
        .frame(maxWidth: .infinity)
        .rotation3DEffect(.degrees(8), axis: (x: 1, y: 0, z: 0), perspective: 0.6)
        .onAppear {
            withAnimation(.easeInOut(duration: 3.2).repeatForever(autoreverses: true)) { float = true }
        }
        .accessibilityHidden(true)
    }

    private var coin: some View {
        ZStack {
            Circle().fill(LinearGradient(colors: [.white, Theme.accentLight], startPoint: .topLeading, endPoint: .bottomTrailing))
            Circle().strokeBorder(Theme.accent.opacity(0.5), lineWidth: 2).padding(3)
            Text("$").font(Theme.display(16)).foregroundStyle(Theme.accentDeep)
        }
        .frame(width: 30, height: 30)
        .glow(.white, radius: 8, strength: 0.5)
    }

    private func miniCard<Content: View>(width: CGFloat, height: CGFloat, @ViewBuilder content: () -> Content) -> some View {
        content()
            .frame(width: width, height: height, alignment: .topLeading)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(LinearGradient(colors: [Color(hex: 0x2A2C74), Color(hex: 0x15173F)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing))
            )
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(LinearGradient(colors: [.white.opacity(0.5), .white.opacity(0.05)],
                                             startPoint: .topLeading, endPoint: .bottomTrailing), lineWidth: 0.8))
            .shadow(color: .black.opacity(0.45), radius: 14, y: 10)
    }
}

/// Small miniature for empty states: a shield on a glowing pedestal.
struct ShieldMiniature: View {
    @State private var pulse = false

    var body: some View {
        ZStack {
            Ellipse()
                .fill(Theme.accent.opacity(0.5))
                .frame(width: 120, height: 26)
                .blur(radius: 14)
                .offset(y: 46)
            Ellipse()
                .fill(LinearGradient(colors: [Color(hex: 0x2A2C74), Theme.raised], startPoint: .top, endPoint: .bottom))
                .overlay(Ellipse().strokeBorder(.white.opacity(0.3), lineWidth: 0.8))
                .frame(width: 104, height: 24)
                .offset(y: 42)
            ZStack {
                Circle().fill(Theme.pearl).frame(width: 76, height: 76)
                Image(systemName: "checkmark.shield.fill")
                    .font(.system(size: 34, weight: .bold))
                    .foregroundStyle(Theme.accentGradient)
            }
            .glow(Theme.accent, radius: pulse ? 22 : 12, strength: 0.8)
            .offset(y: pulse ? -4 : 2)
        }
        .frame(height: 130)
        .onAppear {
            withAnimation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true)) { pulse = true }
        }
        .accessibilityHidden(true)
    }
}
