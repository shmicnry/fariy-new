# FairyMacBridge

Read-only macOS helper for TCC probes, running applications, and a bounded
Accessibility Tree snapshot.

```sh
swift build -c release
.build/release/FairyMacBridge status
.build/release/FairyMacBridge applications
.build/release/FairyMacBridge ax-tree com.apple.TextEdit
.build/release/FairyMacBridge ocr /path/to/image.png
```

`status` and `applications` do not require Accessibility permission. `ax-tree`
returns `accessibility_permission_required` until the owner grants access in
System Settings.

OCR only reads an image path explicitly passed by the local server. The helper
does not inject keyboard or pointer events, take screenshots, read arbitrary
screen pixels, write files, or expose arbitrary shell execution. A
production build still requires a stable bundle identity, code signing,
notarization, TCC acceptance on a physical Mac, and review of every exported
Accessibility attribute.
