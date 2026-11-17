# Sources and Rationale

The standards were synthesized from four user-provided Douyin references and the
existing Fairy product architecture. They are applied as principles, not copied
layouts or assets.

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
