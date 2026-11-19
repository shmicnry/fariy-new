# FairyApp SwiftUI package

This package is the native implementation starting point shared by macOS and iOS.

## Current screens

- macOS: `NavigationSplitView` with grouped work, cognition and capability sections; settings stay in a fixed utility region.
- iOS: five-tab `TabView`, large navigation titles, sheets, scrolling and success haptics.
- Initial API hydration uses structure-matched skeleton cards and respects Reduce Motion.
- New approvals use a one-shot symbol bounce; pending work uses progress instead of looping pulse.
- All screens use the same local Fairy API.
- The owner token is stored in Keychain with device-only accessibility.
- Memory correction/forgetting, course assessment, approvals, skill lifecycle and autonomy candidates are actionable from the native UI.
- Eight-second foreground polling keeps native screens close to server state.
- Device-local notifications can be enabled from Settings; APNs still requires signing and Apple credentials.
- Conversation replies can be read with the device's `AVSpeechSynthesizer`.

## Build

Swift Package:

```sh
swift build
swift build --triple arm64-apple-ios17.0-simulator --sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)"
```

Multiplatform Xcode App target:

```sh
xcodebuild -project FairyApp.xcodeproj -scheme FairyApp \
  -destination 'platform=macOS' CODE_SIGNING_ALLOWED=NO build

xcodebuild -project FairyApp.xcodeproj -scheme FairyApp \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
```

The Xcode target uses `Config/Fairy-Info.plist`, an empty iOS entitlements file,
and an App Sandbox entitlement with outbound network access for macOS. It
builds un-signed for simulator and local verification. `Assets.xcassets`
contains a complete iPhone, iPad and macOS AppIcon set generated from the Fairy
SVG, with no alpha channel.

The default local API address is `http://127.0.0.1:8010`. Opening a physical
iPhone requires a trusted HTTPS address. Fairy defaults to loopback-only Host
checking; see `FAIRY_ALLOW_LAN` and `FAIRY_ALLOWED_HOSTS` in the repository
README.

## Not yet included

There is no selected Apple Developer Team, signed archive, APNs entitlement,
microphone speech-recognition entitlement, Live2D/VRM host or real-device test
suite. Local notification permission and TTS require execution on a signed
device app. Un-signed Xcode builds do not imply App Store or TCC acceptance.
