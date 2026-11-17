---
name: fairy-ui-design
description: Design or audit Fairy’s macOS, iPhone, PWA, and native interfaces so structure, state, direct manipulation, and purposeful motion explain the product before helper copy does.
---

# Fairy UI Design

Use this skill when designing, reviewing, or implementing any Fairy surface,
including memory review, learning, model routing, skills, approvals, Mac
operations, autonomy, notifications, PWA, and SwiftUI screens.

Read
[references/design-standards.md](references/design-standards.md) before making
visual or interaction decisions. Read
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
2. Choose the smallest surface that can hold the task. Use the popup selection
   matrix in the standards instead of calling every overlay a “弹窗”.
3. Do not let a backdrop click dismiss a form with unsaved input. Confirmation
   dialogs never dismiss on backdrop click.
4. Use action-specific labels such as “删除来源” or “遗忘这条记忆”. Do not use
   generic “是/否” confirmation labels.
5. Use one border layer. Prefer separators and surface changes for nested rows.
   When a child surface is visibly nested, set its radius with
   `inner_radius = outer_radius - gap`.
6. Motion must answer an action or show system state. Prefer opacity, transform,
   color and small number changes. Never animate layout dimensions, large blur,
   or looping decoration. Respect reduced motion.
7. Preserve platform behavior: macOS uses dense sidebar, toolbar, menus,
   keyboard, drag, hover and adjustable panes; iPhone uses 44pt targets, bottom
   navigation, sheets, safe areas, haptics and gesture-led hierarchy.

## Workflow

1. Inventory the affected pages and identify the primary task on each.
2. Audit explanatory paragraphs and replace those that describe an available
   action, state, hierarchy or transition with functional UI.
3. Specify component type, states, copy, keyboard/focus behavior, mobile
   adaptation, motion and accessibility before editing.
4. Implement with existing product tokens and components before adding new ones.
5. Render desktop, iPhone, dark, reduced-motion, empty, error and populated
   states. Verify no overflow, unnamed controls, inconsistent targets, clipped
   content or browser errors.
6. Test state-preserving behavior: IME composition, dirty forms, scroll
   following, long filenames, split-pane resizing, drawer close behavior and
   notification/update arrival.

Do not copy video frames, component-library layouts or proprietary assets.
Translate their observable principles into Fairy-specific behavior.
