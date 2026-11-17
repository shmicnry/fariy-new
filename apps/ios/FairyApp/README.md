# FairyApp SwiftUI package

This package is the native implementation starting point shared by macOS and iOS.

## Current screens

- macOS: `NavigationSplitView` sidebar with conversation, memory, learning, tasks and settings.
- iOS: bottom `TabView`, large navigation titles, sheets, spring scrolling and success haptics.
- All screens use the same local Fairy API.
- The owner token is stored in Keychain with device-only accessibility.

## Build

```sh
swift build
swift build --triple arm64-apple-ios17.0-simulator --sdk "$(xcrun --sdk iphonesimulator --show-sdk-path)"
```

Opening a physical iPhone requires a trusted HTTPS address. Fairy defaults to loopback-only Host checking; see `FAIRY_ALLOW_LAN` and `FAIRY_ALLOWED_HOSTS` in the repository README.

## Not yet included

There is no signed Xcode app target, App Store archive, APNs entitlement, camera/microphone entitlement, speech permission usage description, push backend, Live2D/VRM host or real-device test suite. The package compiling for macOS and iOS Simulator does not imply App Store or TCC acceptance.
