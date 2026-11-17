# Fairy UI Design Language and Interaction Standard

Version 1.0. This is the normative design reference for Fairy web, PWA, macOS,
and iPhone interfaces.

## 1. Product direction

Fairy is a local-first personal cognition workspace. It helps one owner review
memory, teach source-backed knowledge, configure local and cloud models, grant
scoped abilities, supervise autonomy, and verify what happened.

The interface should feel like a quiet instrument panel: exact, recoverable, and
alive with real state. It should not look like a generic AI chat shell, a SaaS
card gallery, or a marketplace landing page.

The signature is a **trace rail**: a restrained visual relationship among the
action, current state, evidence, permission, and available recovery. Do not turn
it into a decorative timeline on every page. It appears only where provenance or
supervision matters.

## 2. Core rule: design explains function

Before adding helper text, encode the function with one or more of:

- grouping related controls;
- showing the currently selected object;
- presenting the next available action;
- updating content in place;
- showing before/after or locked/unlocked state;
- revealing source and revision history;
- exposing a progress meter, lifecycle stepper, or permission boundary;
- showing a live preview or concrete result.

Keep prose for information users cannot safely infer:

- privacy and external transmission;
- irreversible deletion or forgetting;
- permission scope and permission limits;
- unavailable network, device, model, or TCC capabilities;
- error diagnosis and recovery;
- conflicts, uncertainty, and source eligibility.

Do not use a paragraph to describe an action that the adjacent control can show.
Replace “安装、授权、启用和执行是四个独立步骤” with a lifecycle stepper and
state-aware controls. Replace budget explanation with meters. Replace “views”
with a drawer or page that contains the object.

## 3. Visual tokens

### Color

- Canvas: `#EAF0F3`
- Deep canvas: `#DFE8ED`
- Surface: `#FFFFFF`
- Ink: `#1A2E3D`
- Secondary ink: `#506779`
- Muted ink: `#566B79`
- Accent: `#235F79`
- Focus: `#338AAB`
- Danger: `#9E3E3E`
- Warning: `#7D5B21`

Use one accent for selection, primary action, progress, and live status. Semantic
colors carry meaning only. Do not add hue gradients, gradient text, colored glows,
or neon shadows.

### Type

- UI family: SF Pro Text / system Apple sans.
- Body: 14–15 px; labels: 12–13 px; captions: 10–11 px.
- Headings use size and color before weight; avoid weights above 600.
- Use sentence case. No all-caps tracked labels.
- Use tabular numbers for budgets, versions, scores and counts.

### Space and shape

- Base grid: 4 px.
- Desktop controls: 34–38 px; iPhone controls: at least 44 px.
- Sidebar rows: 34 px with 2 px gaps.
- Cards/panels: 12–18 px radius.
- Dialog: 16 px radius; drawer: 18 px.
- Nested radius: `inner = outer - gap`, minimum 4 px.
- Avoid a bordered card inside a bordered panel. Use separators and surface steps.

### Materials

- macOS sidebar and mobile tabs may use blur and translucent surface.
- Content remains on quiet neutral surfaces.
- Depth uses hairlines and surface steps. Shadows are soft, neutral, and limited
  to floating surfaces.

## 4. Popup and navigation selection

| Need | Use | Behavior |
|---|---|---|
| Explain an icon or short unfamiliar term | Tooltip | Appears on hover/focus; never contains actions |
| Confirm a successful or non-blocking background event | Toast | Fades automatically; no action required |
| Confirm one local action with context | Popconfirm | Anchored to trigger; explicit action label |
| Communicate blocking error or required choice | Alert | Persistent until resolved |
| Confirm a focused, short decision | Modal dialog | No backdrop dismissal for destructive or dirty state |
| Review or edit a long object without leaving context | Drawer / sheet | Desktop right drawer; iPhone sheet |
| Complete a multi-step task or compare many objects | Page | Full workspace, back navigation and stable draft |

Rules:

1. Use the smallest surface that fits. Do not use a modal for long forms.
2. A dirty form does not close on backdrop click.
3. Confirmation labels name the action: “删除来源”, “遗忘这条记忆”, “停用技能”.
4. Avoid a disclosure row followed by a second confirmation for the same action.
5. Tooltips are not available on touch-only devices; repeat the accessible name
   in the control’s accessible label.
6. Drawers preserve the underlying page and scroll position.

## 5. Functional component patterns

### Button hierarchy

- Primary: one per task surface.
- Secondary: search, inspect, refresh, navigate, run a read-only query.
- Danger: destructive or irreversible operation.
- Processing: disable the trigger, show progress, retain width where practical.
- Completion: show a short action-specific Toast.

### Forms

- Visible labels remain after input.
- Help text appears only for privacy, format, or safety constraints.
- Inline validation describes the fix.
- Enter submits only when composition has ended; IME candidate selection must
  never send the message.
- Shift+Enter inserts a line break in message composers.

### Lists and records

- Same record type uses the same alignment and action order.
- Nested groups use separators, not a second border layer.
- A record’s status is a small semantic marker, not color applied to all text.
- Destructive controls sit after safe controls.
- Long filenames truncate in the middle and always preserve the extension.

### Metrics and budgets

- One label, one tabular figure, one comparison or limit.
- Use a progress meter for a real bounded resource.
- Animate a number from its previous value to the current value once, with Ease
  Out, unless reduced motion is enabled.

### Skill lifecycle

Show `安装 → 授权 → 启用 → 执行` as a stepper. The button changes with state;
permission scope, expiry, and revocation remain visible as data.

### Permission and provenance

- Show owner, source, revision and validity together.
- Use a trace rail only when action-to-evidence linkage matters.
- TCC, cloud, and external-service states must state whether they are unprobed,
  denied, granted, configured, or available.

### Empty and error states

- Empty state includes the direct next action.
- Error state names what happened and how to recover.
- Unavailable functions remain visibly unavailable with the actual blocker.

## 6. Chat and AI interaction

- Preserve user drafts across background page updates.
- Stop auto-follow as soon as the user scrolls upward.
- Show “跳到最新” when new content arrives outside the viewport.
- Do not scroll the entire document when only the message transcript changed.
- Use typewriter-like streaming only for actual model streaming. Never animate
  static prose for decoration.
- Separate user text, assistant response, route/provider, evidence, and tool
  state visually.
- A pending answer must remain interruptible.
- Memory writes remain proposals until explicitly reviewed.

## 7. macOS behavior

- Persistent sidebar with grouped navigation.
- Toolbar owns global actions such as notifications and connection.
- Hover and focus reveal secondary affordances.
- Support keyboard navigation, shortcuts, and context menus where useful.
- The sidebar is resizable by drag:
  - pointer drag changes width;
  - Arrow Left/Right changes by 16 px;
  - Home/End select limits;
  - Escape or double-click returns to default;
  - width persists per user.
- Panes must never be resized so far that content becomes unreadable.
- Drawers open from the trailing edge; dialogs stay compact.

## 8. iPhone behavior

- Bottom tab bar with five primary destinations.
- Large titles and safe-area spacing.
- Controls and tap targets at least 44 pt.
- Sheets for editing and inspection; no persistent multi-pane layout.
- Primary actions belong in the lower half where practical.
- Avoid hover-only information.
- Haptic feedback confirms selection, success, warning and destructive boundaries.
- Reduce motion replaces springs with immediate state changes.

## 9. Motion system

Use motion to explain a change, not to decorate a static interface.

| Pattern | Fairy use |
|---|---|
| Press scale | Button/tap feedback, 0.97–0.99 |
| Surface transition | Hover, focus, selection |
| Drawer spring | Drawer enter/exit, 180–240 ms Ease Out |
| One page reveal | Initial route content, once |
| Toast rise/fade | Background completion |
| Number tween | Budget/score changes |
| Progress fill | Real bounded task |
| Skeleton shimmer | Only while data is unresolved |
| Row stagger | One short list entrance, max ~40 ms stagger |
| Typewriter | Real streaming model output only |
| Spotlight / magnetic / 3D tilt / border beam / text scramble | Not used in core workflows |
| Parallax / marquee / looping glow | Not used in Fairy |

One easing family and a small duration set:

- feedback: 120–160 ms;
- surface enter: 180–240 ms;
- page reveal: 220 ms;
- number tween: 240–320 ms.

Animate opacity, transform, color, background and border. Do not animate width,
height, margins, top/left, or large blur filters. Always respect
`prefers-reduced-motion`.

## 10. Hidden AI-interface details

- Chinese IME composition has priority over Enter submission.
- User-upward scroll stops forced auto-follow.
- One border layer per component hierarchy.
- Nested corner radii remain concentric.
- Split panes support reset, keyboard adjustment and bounded drag.
- Long filenames preserve their suffix.
- Background updates preserve dirty drafts and scroll position.
- Restored windows retain pane sizes and selected route.

## 11. Visual references

The following component libraries are references for qualities, not assets to
copy:

- BoardUI: restrained Apple-style density for dashboards and admin surfaces.
- Bencho: button, menu and slider interaction polish.
- HeroUI Pro: mature, legible product admin patterns.
- beUI Pro: stronger brand composition and varied section rhythm.
- Libraries.dev: multiple design directions.
- Watermelon UI: AI-state visualization and future-facing motion cues.

For Fairy, use the Apple-style density and interaction polish. The lived-in
“instrument panel” should carry the product identity; avoid glossy orbs,
fantasy-neon AI signifiers and decorative particle fields outside the cognitive
map where the metaphor is functional.

## 12. Review checklist

- Can the primary task be understood without a helper paragraph?
- Does each popup use the smallest correct surface?
- Are dirty forms protected from accidental dismissal?
- Are destructive confirmations action-specific?
- Is every nested hierarchy single-bordered and radius-consistent?
- Does the layout preserve information density on macOS and touch clarity on iPhone?
- Are keyboard, IME, scroll-follow, long-text and resize cases handled?
- Is there one primary action and one memorable product moment per page?
- Does motion explain state change and stop under reduced motion?
- Are source, permission, uncertainty and unavailable states explicit?
