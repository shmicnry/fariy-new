# Interaction Pattern Playbook

Read this reference when implementing Fairy navigation, loading, contained
disclosure, continuous corners or named animation effects. These are product
principles translated from five public design references, not templates to copy.

## 1. Sidebar hierarchy

Use a three-region structure on macOS and dense web workspaces:

```text
┌──────────────────────────┐
│ identity, workspace,     │ fixed
│ connection context       │
├──────────────────────────┤
│ grouped destinations     │ scrolls
│                          │
├──────────────────────────┤
│ settings, help, version  │ fixed
└──────────────────────────┘
```

1. Group entries by the owner's work, not by data model or API namespace.
2. Use short noun headings with sentence case. Avoid uppercase tracked labels.
3. Control spacing between groups; do not add a card and border around each.
4. Use one filled selected row, one accent marker and full-strength ink. Keep
   idle items in secondary ink and avoid a second active-like hover state.
5. Put low-frequency access such as settings, help and about at the fixed
   bottom. Consolidate entries when functions truly duplicate; do not hide
   capabilities merely to shorten the list.
6. Middle region: `min-height: 0; overflow: auto; overscroll-behavior: contain`.
   Keep focus visible while scrolling and preserve the selected row.
7. iPhone uses bottom navigation plus sheets or a pushed page for overflow. The
   desktop sidebar is not a mobile pattern.

For Fairy, preserve visibility of operational groups such as 工作台, 记忆与学习,
能力与控制, and 自主性. Move version, help, diagnostics and account-level settings
to the fixed utility region.

## 2. Loading state selection

| Missing information | Correct state | Required behavior |
|---|---|---|
| Known layout, unknown data | Structure-matched skeleton | Mirror block geometry; delay briefly; no invented labels; announce completion |
| Measurable operation | Determinate progress | Follow real values; show stage; cap uncertainty; support cancel when possible |
| Image/video with reserved box | Blur-up placeholder | Preserve aspect ratio; use local/derived preview; cached media appears immediately |
| Very short action, unknown structure | Compact spinner or button progress | Keep control width stable; disable duplicate submission |
| Long unknown operation | Task/run surface | Show started time, current stage, logs summary, cancel, retry and recovery |

Silent failures are worse than visible uncertainty. Never smooth progress past
the real value or leave an endless skeleton when the task has entered a durable
run state.

### Skeleton

- Match the final row, chart, list or panel geometry.
- Use neutral surface steps at low contrast.
- Prefer one short sweep only while unresolved. Pause offscreen; disable on
  reduced motion.
- Replace the skeleton at its measured bounds to avoid layout shift.
- Do not skeletonize a layout that is already cached or visually ready.

### Progress

- Use determinate progress for uploads, installs, learning ingestion, model
  downloads, Mac operations and autonomy runs when a reliable fraction exists.
- If exact fraction is unavailable, combine elapsed time with named stages.
- A visual estimate may ease between real samples, but labels and percentages
  must reflect measured values.
- Completion is shown only after the backend or verifier confirms success.

### Blur-up

- Reserve the image's aspect ratio before request completion.
- Draw a local color, reduced image or documented placeholder first.
- Transition blur and opacity together when the final image decodes.
- Do not blur critical text; use a text skeleton or real value instead.
- Respect reduced motion by swapping the image without a blur transition.

## 3. Contained disclosure

Use compact disclosure when the closed state communicates enough to decide
whether opening is useful.

| Pattern | Closed state | Good Fairy use | Avoid |
|---|---|---|---|
| Avatar stack | Overlaps a few people, then `+N` | Participants in an approval or collaborative task | Decorative social proof |
| Progress-as-surface | The filled background is the meter | Install, download, ingestion or budget progress | Using tint as progress without a value |
| Horizontal accordion | Icons or short headers remain visible | Mutually exclusive tool/device details | Hiding all labels or allowing hover-only access |
| Anchored tray | One stable parent control | Actions for selected skill, source or device | Moving the parent when the tray opens |
| Scrub-strip picker | Selected value remains readable | Touch-only numeric or option picker | Critical action without keyboard/tap alternative |
| Pull/click summary | Capsule shows count or headline | Notifications, sources, diagnostics and run summaries | Reporting state changes only after expansion |

Requirements:

- the trigger has an accessible name and `aria-expanded`;
- the expanded region keeps its identity and does not replace the whole page;
- focus moves into a modal-like region or remains on an inline control according
  to interaction type, then returns on close;
- one expanded item at a time unless comparison requires more;
- preserve scroll, draft and selected item;
- touch handles are at least 44 pt and drag thresholds do not hijack page scroll;
- summarise unread/error/live changes in the collapsed state.

## 4. Continuous curvature

The visual difference is not the radius number. A circular-corner join changes
curvature abruptly where a straight edge meets the arc. Continuous curvature
starts bending earlier and changes gradually.

Use continuous corners on:

- macOS-native cards, sheets and window-like containers;
- iPhone cards, grouped rows and floating controls where the platform uses it;
- web cards, dialogs and rounded rectangular containers after progressive
  enhancement;
- nested surfaces only when the outer and inner treatments remain concentric.

Do not use it on true circles, capsules, avatars or decorative blobs.

### Web

```css
.continuous-surface {
  border-radius: var(--radius);
}

@supports (corner-shape: squircle) {
  .continuous-surface {
    corner-shape: squircle;
  }
}
```

Test the actual WebView and Safari version. Unsupported browsers must retain the
fallback without missing backgrounds, borders or focus rings.

### SwiftUI

```swift
content
  .clipShape(
    RoundedRectangle(cornerRadius: radius, style: .continuous)
  )
```

For design handoff, write “continuous curvature” or “corner smoothing”, not merely
“larger radius”. Preserve the tokenized radius; changing the corner algorithm
does not justify arbitrary radii.

## 5. Named motion vocabulary

Choose by function first. The name helps implementation; it does not make an
effect appropriate.

| Function | Approved vocabulary | Fairy use |
|---|---|---|
| Direct manipulation | press scale, drag snap, layout reorder | Reordering a real list, moving a skill token, resizing a pane |
| Focus | smooth cursor focus, focus dimming | Selecting one source or device while preserving context |
| Feedback | tap ripple, progress fill, spring return | Confirming a tap, real upload or reversible movement |
| Hierarchy | matched bounds, mask reveal, folded advance | Keeping an object identity while moving from summary to detail |
| Data change | number tween, progress fill, scrub update | Budget, score, ingestion or time changes |
| Provenance | path draw, trace reveal | Connecting answer to evidence, permission or recovery |
| Content entrance | fade and rise, short stagger, scale fade | One route reveal or one newly created object |
| Text change | letter reveal, typewriter, rolling swap | Live streaming, truly changing status or a single authored moment |

Use these as the source vocabulary:

- 游标平滑聚焦、点击波纹、磁吸跟随、拖拽吸附；
- 悬停抬升、3D 翻转、堆叠展开、布局重排；
- 弹簧回弹、落地弹跳、挤压拉伸、惯性缓停；
- 遮罩揭示、推拉切换、匹配变形、折叠推进；
- 呼吸脉冲、高光扫过、模糊到清晰、聚光追踪；
- 圆角变化、形状变换、沿路径运动、描边绘制；
- 逐字显现、文字相错入场、打字机、文字滚动切换；
- 淡入淡出、基础位移、缩放聚焦、旋转滚动。

Default parameters:

- tactile feedback: 120–160 ms;
- surface enter: 180–240 ms;
- route/content reveal: 220–320 ms;
- stagger: no more than five visible items, about 30–40 ms apart;
- progress fill: ease toward state changes, never hide real failure;
- blur-up: a single decode-triggered transition, no loop.

Use one easing family per hierarchy. Prefer transform, opacity, color, background
and clip/mask. Respect `prefers-reduced-motion`; reduced motion changes state
without spatial travel.

Rejected in core Fairy workflows:

- magnetic buttons and cursor attraction;
- 3D card tilt and card flips for ordinary navigation;
- decorative border beams, shimmer on populated data, and looping glows;
- text scramble or typewriter for static content;
- hover lift applied indiscriminately to every card;
- long parallax, marquee and scroll hijacking;
- pulse around every badge or notification.

## 6. Verification

1. Inspect the stable layout before animation.
2. Capture the loading, loaded, empty, error, collapsed and expanded frames.
3. Check at 200 ms and after completion, not only the final screenshot.
4. Test at 1440 px, a resized macOS pane and 390 px iPhone width.
5. Repeat with keyboard, touch and `prefers-reduced-motion`.
6. Verify no layout shift, hidden draft, lost focus, double scrollbar, false
   progress, unexplained pulse or browser error.
