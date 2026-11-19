---
name: fairy-ui-design
description: Design or audit Fairy’s macOS, iPhone, PWA, and native interfaces so navigation, loading, disclosure, shape, state, direct manipulation, and purposeful motion explain the product before helper copy does.
---

# Fairy UI Design

Use this skill when designing, reviewing, or implementing any Fairy surface,
including memory review, learning, model routing, skills, approvals, Mac
operations, autonomy, notifications, PWA, and SwiftUI screens.

Read
[references/design-standards.md](references/design-standards.md) before making
visual or interaction decisions. Read
[references/interaction-patterns.md](references/interaction-patterns.md) when
changing sidebars, loading states, progressive disclosure, continuous corners,
or named motion effects. Read
[references/sources-and-rationale.md](references/sources-and-rationale.md) when
traceability to the source material matters.

## Direction

- Product: a local-first personal cognition workspace where the owner reviews
  memory, teaches knowledge, grants scoped abilities, and supervises autonomy.
- Character: quiet, exact, alive.
- World: a macOS observatory and instrument panel, with provenance and state
  rails rather than decorative AI imagery.
- Moments: source provenance and the current state of cognition or execution.
- Signature: a restrained trace rail that connects a visible action or answer
  to its state, evidence, permission, and recoverability.

## Required decisions

1. Explain a function through at least one visible mechanism: spatial grouping,
   direct control, selected state, live result, before/after transition, or
   recoverable history. Use prose only for safety, privacy, irreversible effects,
   unavailable capabilities, and error recovery.
2. Keep the macOS sidebar legible before removing capability: fixed identity
   area, grouped and scrollable middle navigation, and fixed low-frequency
   tools. Show one unambiguous current location.
3. Choose the smallest surface that can hold the task. Use the popup selection
   matrix in the standards instead of calling every overlay a “弹窗”.
4. Match the wait state to the missing information. Use geometry-shaped
   skeletons when layout is known, determinate progress for measurable work,
   and aspect-ratio-reserved blur-up media for images. Use a spinner only for a
   short wait with unknown structure.
5. Use contained disclosure only when the collapsed control still communicates
   the hidden object, count, progress, or next action. Expanded state must be
   reversible and must not depend on hover or gesture alone.
6. Use continuous-curvature corners on Apple-native rounded rectangles and as a
   progressive enhancement on web. Preserve ordinary `border-radius` and
   concentric nesting as the fallback.
7. Do not let a backdrop click dismiss a form with unsaved input. Confirmation
   dialogs never dismiss on backdrop click.
8. Use action-specific labels such as “删除来源” or “遗忘这条记忆”. Do not use
   generic “是/否” confirmation labels.
9. Use one border layer. Prefer separators and surface changes for nested rows.
   When a child surface is visibly nested, set its radius with
   `inner_radius = outer_radius - gap`.
10. Motion must answer an action or show system state. Name an effect before
   implementing it. Prefer opacity, transform,
   color and small number changes. Never animate layout dimensions, large blur,
   or looping decoration. Respect reduced motion.
11. Preserve platform behavior: macOS uses dense sidebar, toolbar, menus,
   keyboard, drag, hover and adjustable panes; iPhone uses 44pt targets, bottom
   navigation, sheets, safe areas, haptics and gesture-led hierarchy.

## Workflow

1. Inventory the affected pages, sidebar groups, overlays, waits, and disclosure
   controls. Identify the primary task on each.
2. Audit explanatory paragraphs and replace those that describe an available
   action, state, hierarchy or transition with functional UI.
3. Specify component type, collapsed/loading/error/populated states, copy,
   keyboard/focus behavior, mobile adaptation, motion vocabulary and
   accessibility before editing.
4. Implement with existing product tokens and components before adding new ones.
5. Render desktop, iPhone, dark, reduced-motion, fast/slow loading, empty,
   error, collapsed, expanded and populated states. Verify no overflow, unnamed
   controls, inconsistent targets, clipped content, baked-in placeholders,
   unexpected layout shift or browser errors.
6. Test state-preserving behavior: IME composition, dirty forms, scroll
   following, long filenames, split-pane resizing, fixed/scrollable sidebar
   regions, disclosure focus return, drawer close behavior and
   notification/update arrival.

Do not copy video frames, component-library layouts or proprietary assets.
Translate their observable principles into Fairy-specific behavior.
