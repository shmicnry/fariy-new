# Sources and Rationale

The standards were synthesized from nine user-provided Douyin references, Apple
platform behavior and the existing Fairy product architecture. They are applied
as principles, not copied layouts or assets.

## Overlay taxonomy

Source: Ludi, “Vibe知识大赏丨别再管所有弹出来的东西都叫‘弹窗’了！”

- https://www.douyin.com/video/7698358547440094502
- Published 2026-10-19.
- Extracted topic: Tooltip, Toast, Alert, Modal, Popconfirm; choose popup,
  drawer, or page based on content length and whether the user needs context.
- Adopted: a selection matrix, no blanket “popup”, no dirty-form backdrop
  dismissal, no redundant confirmation, and action-specific confirmation labels.

## Motion vocabulary

Source: 小刷AI全栈, “别再让AI加点高级动画了！16种UI动效，让你说清想要的效果”.

- https://www.douyin.com/video/7707202818528910159
- Published 2026-11-12.
- 16 cited effects: spotlight, scroll reveal, border beam, magnetic button,
  scroll storytelling, 3D tilt, text scramble, shimmer, parallax, count-up,
  hover lift, typewriter, stagger, marquee, spring, easing.
- Adopted selectively: count-up only for real metrics, shimmer only for loading,
  typewriter only for actual streaming, stagger only for one list entrance,
  spring only for sheets/drawers and direct manipulation.
- Rejected for core Fairy workflows: border beam, magnetic buttons, 3D tilt,
  text scramble, parallax, marquee and decorative loops.

## Visual direction

Source: 派大鑫, “想要 Vibecoding 出来的界面美观，那就不要错过这6个宝藏组件库”.

- https://www.douyin.com/video/7704266431650993763
- Published 2026-11-04.
- Extracted directions: Apple-style density, fine interaction detail, mature
  product admin, brand composition, future AI states, multiple reference styles.
- Adopted: Apple-style shell and density for Fairy, refined control feedback,
  one functional AI-state moment, and restrained brand character.
- The named libraries are references only. No component code or visual asset is
  copied.

## AI-interface details

Source: Ludi, “大厂AI界面的5个隐藏 第二弹”.

- https://www.douyin.com/video/7699520911870856483
- Published 2026-10-23.
- Extracted details: IME-safe Enter, stop auto-follow when scrolling up with
  “jump to latest”, one border layer, concentric radii, resettable split panes,
  and filename suffix preservation.
- Adopted directly in Fairy’s composer, conversation scroller, row hierarchy,
  resizable sidebar and long filename headings.

## Sidebar grouping and fixed regions

Source: CoverAI, “侧边栏太乱？一个入口不删，也能变清爽”.

- https://www.douyin.com/video/7703067552864802020
- Published 2026-11-01.
- Extracted details: group entries, label groups, separate groups with spacing,
  make the selected row unmistakable while muting idle items, move low-frequency
  entries to the fixed bottom, and scroll only the middle when the list is long.
- Adopted: three-region macOS sidebar, one selected treatment, fixed utility
  region and no nested scrollbar. Consolidation remains allowed when entries
  duplicate one function.

## Loading-state vocabulary

Source: BeiYu 北煜, “加载那 3 秒，别只给一个转圈”.

- https://www.douyin.com/video/7704635591618514227
- Published 2026-11-05.
- Extracted patterns: left-to-right skeleton sweep, progress following real
  completion, and blur-to-clear media.
- Adopted with safeguards: structure-matched skeletons, measured progress,
  reserved media aspect ratios, cache-aware instant display, long-task recovery
  and accessibility announcements.

## Motion effect library

Source: 夏夏（Ai 版）, “第8集 | 一口气看完！Remotion 32种动效合集！”.

- https://www.douyin.com/video/7709012882524081446
- Published 2026-11-17.
- Extracted categories: cursor interaction, cards, spring and inertia,
  transitions, emphasis, shape/path, text, and basic movement.
- Adopted: effect names as implementation vocabulary and a function matrix in
  `interaction-patterns.md`.
- Rejected for ordinary product UI: indiscriminate hover lift, magnetic cursor,
  3D tilt/flip, cinematic reveals, looping pulse, text scramble and decorative
  spotlight/sweep.

## Contained expansion

Source: CoverAI, “6 个收起又展开的组件”.

- https://www.douyin.com/video/7707912737439002346
- Published 2026-11-14.
- Extracted patterns: expanding avatar stack, progress fill as a surface,
  horizontal accordion, anchored component tray, touch scrub picker and
  pull/click summary.
- Adopted: context-preserving compact disclosure, reversible state, stable
  parent, touch-safe handles and summary badges. Removed demonstrative motion
  where it does not carry product meaning.

## Continuous curvature

Source: Ludi, “苹果的圆角，为什么看着更顺？”.

- https://www.douyin.com/video/7704658078930636095
- Published 2026-11-05.
- Extracted principle: continuous curvature avoids the abrupt slope and curvature
  change where a straight edge meets a circular radius.
- Implemented as progressive enhancement with CSS `corner-shape: squircle`,
  ordinary `border-radius` fallback, and SwiftUI
  `RoundedRectangle(..., style: .continuous)`.
- Browser and platform references:
  - https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/Properties/corner-shape
  - https://developer.apple.com/documentation/swiftui/roundedcornerstyle/continuous

## Existing Fairy constraints

- macOS and iPhone follow Apple HIG rather than a cross-platform visual port.
- Memory and source review require visible provenance and recovery.
- Autonomy and permissions require explicit limits and state.
- The product already has a quiet cool-neutral visual language; the standards
  preserve it rather than replacing it for novelty.

## Attribution

Some review language and method are informed by the `unslop` skill by Damir
Sokolovsky, licensed CC BY 4.0. Fairy’s standards are a product-specific
adaptation and do not reproduce the skill’s examples or assets.
