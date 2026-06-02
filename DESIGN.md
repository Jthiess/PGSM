# Design System & Style Guide

This document describes the look, feel, and underlying design tokens of the
**Jack Thiess portfolio** website. Use it as the reference when building other
sites that should share the same identity — a dark, card-based, "vCard" style
interface with purple accents.

---

## 1. Design Philosophy

The site is a **single-page, dark-themed personal card**. The whole experience
should feel:

- **Dark and calm** — near-black backgrounds, no harsh white.
- **Tactile / layered** — every surface is a rounded card sitting on a darker
  background, separated by subtle borders and soft shadows.
- **Focused** — one accent color (purple) draws the eye to interactive and
  important elements. Everything else is grayscale.
- **Soft** — large border radii, gentle fades, smooth transitions. Nothing is
  sharp or abrupt.

When extending this to a new site, the test is: *"Does it look like the same
person made it?"* Keep the dark grayscale base, the rounded cards, the single
purple accent, and the Poppins type.

---

## 2. Color Palette

All colors are defined as CSS custom properties on `:root`. Reuse these exact
variables on new sites so palettes stay identical.

### 2.1 Solid Colors

| Token | Value | Looks like | Primary use |
|---|---|---|---|
| `--smoky-black` | `hsl(0, 0%, 7%)` | Near-black | **Page background** (the layer behind all cards) |
| `--eerie-black-2` | `hsl(240, 2%, 12%)` | Very dark gray | **Card backgrounds** (sidebar, articles, modal) |
| `--eerie-black-1` | `hsl(240, 2%, 13%)` | Very dark gray | Inner fill of icon boxes / nested surfaces |
| `--onyx` | `hsl(240, 1%, 17%)` | Dark gray | Pills, badges, scrollbar track, small inset surfaces |
| `--jet` | `hsl(0, 0%, 22%)` | Mid-dark gray | **Borders & separators** between cards/sections |
| `--light-gray` | `hsl(0, 0%, 84%)` | Light gray | **Body text** |
| `--light-gray-70` | `hsla(0, 0%, 84%, 0.7)` | Muted light gray | Secondary/label text, hover-dim states |
| `--white-2` | `hsl(0, 0%, 98%)` | Off-white | **Headings** |
| `--white-1` | `hsl(0, 0%, 100%)` | Pure white | Text on filled badges/pills |
| `--purp-one` | `hsl(253, 100%, 72%)` | Vivid purple | **Primary accent** — active states, icons, links, focus |
| `--purp-two` | `rgb(115, 90, 206)` | Deeper purple | Secondary accent — dates/metadata in timeline |

### 2.2 Gradients

Gradients are used sparingly to add depth on cards, borders, and accents.

| Token | Definition | Use |
|---|---|---|
| `--bg-gradient-onyx` | onyx → dark, top-left to bottom-right | Avatar boxes, large rounded image frames |
| `--bg-gradient-jet` | translucent jet over eerie-black | Inner fill of cards that have a gradient border (`::before` layer) |
| `--bg-gradient-purple-1` | solid purple → transparent | Hover glow on the "show contacts" button |
| `--bg-gradient-purple-2` | translucent purple over eerie-black | Hover inner fill of that same button |
| `--border-gradient-onyx` | gray → transparent, diagonal | **Card / icon "border" layer** — sits under content, a 1px inset reveals it as a faux gradient border |
| `--text-gradient-purple` | purple → deeper purple, left to right | The little underline under section titles, timeline dots, accent marks |

### 2.3 When to Use Which Color

- **Background of the whole page** → `--smoky-black`. Always the darkest layer.
- **Any panel, card, or container** → `--eerie-black-2` with a `--jet` border.
- **Borders, dividers, separators** → `--jet`.
- **Headings** (`h2`–`h5`) → `--white-2`.
- **Paragraph / descriptive text** → `--light-gray`, weight 300.
- **Labels, captions, metadata** → `--light-gray-70` or `--onyx`-backed pills.
- **Anything interactive or "selected"** (active nav, links on hover, icons,
  focus outlines, the text-selection highlight) → `--purp-one`. This is the
  *only* saturated color on the page; spend it carefully so it keeps meaning.
- **Accent details** (title underlines, timeline dots) → `--text-gradient-purple`.

> **Rule of thumb:** grayscale for structure and content, purple for attention.
> If a new element isn't interactive or important, it should be grayscale.

---

## 3. The "Layered Card" Pattern

This is the single most defining visual motif. Almost everything is a card:

```
body (--smoky-black)
 └─ card (--eerie-black-2, 1px --jet border, radius 20px, shadow-1)
     └─ nested surface (gradient border via ::before inset 1px)
```

**Core card** (`.sidebar`, `article`):
- `background: var(--eerie-black-2)`
- `border: 1px solid var(--jet)`
- `border-radius: 20px`
- `padding: 15px` (mobile) → `30px` (≥580px)
- `box-shadow: var(--shadow-1)` → `--shadow-5` on large screens

**Gradient-border card** (`.content-card`, `.service-item`, `.icon-box`):
- The element's own background is a gradient (`--border-gradient-onyx`).
- A `::before` pseudo-element with `inset: 1px` is filled with the solid/gradient
  body color (`--bg-gradient-jet` or `--eerie-black-1`) and `z-index: -1`.
- The 1px gap that peeks out reads as a soft, fading gradient border.

Replicate this `::before { inset: 1px }` trick whenever you need a card that
looks subtly outlined rather than flatly filled.

---

## 4. Typography

- **Font family:** `'Poppins', sans-serif` (`--ff-poppins`). Load from Google
  Fonts. This is the only typeface.
- **Weights used:** 300 (body), 400, 500 (names/subheads), 600 (titles on
  larger screens). Tokens: `--fw-300` … `--fw-600`.
- **Headings** use `--white-2` and `text-transform: capitalize`.
- **Body** uses `--light-gray`, weight 300, `line-height: 1.6`.

### Font Size Scale (mobile → ≥580px)

| Token | Mobile | ≥580px | Typical use |
|---|---|---|---|
| `--fs-1` | 24px | 32px | Page/article title (`.h2`) |
| `--fs-2` | 18px | 24px | Section heading (`.h3`) |
| `--fs-3` | 17px | 26px | Name in sidebar |
| `--fs-4` | 16px | 18px | Card titles (`.h4`) |
| `--fs-6` | 14px | 15px | Body / descriptive text |
| `--fs-7` | 13px | 15px | Contact values, small headings |
| `--fs-8` | 11px | 12px | Labels, badges, nav links |

The scale is bumped up at the 580px breakpoint via redefined `:root` variables —
the same class names automatically grow. Keep this approach: **change the tokens
at breakpoints, not the rules.**

---

## 5. Shape, Spacing & Elevation

- **Border radius:** generous and consistent.
  - Large cards: `20px`
  - Medium cards / modals: `14px` (→ `20px` on larger screens)
  - Icon boxes: `8px` (→ `12px`)
  - Pills/badges: `8px`
  - Avatar frames: `20px`–`30px`
- **Spacing:** card padding `15px` → `30px`; section gaps ~`15–35px`; consistent
  `15–20px` gaps in flex/grid layouts.
- **Shadows** (`--shadow-1`, `--shadow-2`, `--shadow-5`): all soft, black,
  low-opacity (`0.125`–`0.25`), large blur. They lift cards off the background
  gently — never hard or dark. On ≥1024px screens shadow opacity is *reduced*
  (`0.125`) so big layouts feel lighter.

```
--shadow-1: -4px 8px 24px hsla(0,0%,0%,0.25)   /* default card lift */
--shadow-2: 0 16px 30px hsla(0,0%,0%,0.25)     /* buttons, inner cards */
--shadow-5: 0 24px 80px hsla(0,0%,0%,0.25)     /* modal, big-screen cards */
```

---

## 6. Motion & Interaction

- **Transitions:** `--transition-1: 0.25s ease` (most hovers/toggles),
  `--transition-2: 0.5s ease-in-out` (panel expand/collapse, reveals).
- **Page change** fades in: `@keyframes fade` from `opacity 0.55 → 1` over 0.25s.
- **Hover/focus** behavior:
  - Nav links shift from `--light-gray` → dim, and the **active** link is
    `--purp-one`.
  - The "show contacts" button glows purple on hover (purple gradients swap in).
  - Modal opens with a `scale(1.2) → scale(1)` + opacity transition behind a
    blurred-black overlay (`opacity 0.8`).
- **Focus outline:** `--purp-one`. Keep keyboard focus visible and on-brand.
- **Text selection:** `::selection` is purple background with smoky-black text.
- **Custom scrollbars:** thin (5px), `--onyx` track, `--purp-one` thumb.
- **Navbar** is frosted glass: `hsla(240,1%,17%,0.75)` + `backdrop-filter: blur(10px)`.

> Keep motion subtle and quick. Nothing bounces or slides far; things fade,
> expand, and lift.

---

## 7. Layout & Responsiveness

A mobile-first, single-column layout that progressively widens:

| Breakpoint | Behavior |
|---|---|
| **base (mobile)** | Single column. Sidebar collapses to a name + expandable contacts. Navbar is fixed to the **bottom** of the screen. |
| **≥580px** | Larger type, more padding, cards fixed to `520px`, service items go horizontal. |
| **≥768px** | Cards `700px`; contacts list becomes 2 columns. |
| **≥1024px** | Cards `950px`; **two-column layout** — sticky sidebar on the left, content on the right. Navbar moves to the **top-right** of the content card. |
| **≥1250px** | Fluid widths (max 1200px main), custom body scrollbar, full desktop "vCard" experience. |

Key idea: the **navbar relocates** (bottom bar on mobile → top-right tab strip on
desktop) and the **sidebar becomes a persistent rail** on wide screens. Preserve
this adaptive behavior for a consistent cross-device feel.

---

## 8. Iconography & Imagery

- **Icons:** [Ionicons](https://ionicons.com/) (v7), loaded via CDN
  (`ionicons.esm.js`). Outline style (e.g. `mail-outline`, `school-outline`).
  Stroke width is thinned (`--ionicon-stroke-width: 35px`) for an elegant look.
  Icons sit inside gradient-bordered **icon boxes** and render in `--purp-one`.
- **Custom skill icons:** small (40px) PNGs in `Images/Icons/`.
- **Photos:** rounded heavily (`border-radius: 16–30px`), framed in
  `--bg-gradient-onyx` avatar boxes.
- **Favicon:** `Images/Icons/Favicon.png`.

---

## 9. Component Cheat-Sheet

| Component | Recipe |
|---|---|
| **Card / panel** | `--eerie-black-2` bg, `1px --jet` border, radius 20px, `--shadow-1` |
| **Gradient-border card** | `--border-gradient-onyx` bg + `::before { inset:1px; background:--bg-gradient-jet }` |
| **Icon box** | 30–48px, radius 8–12px, gradient border, `--purp-one` icon |
| **Pill / badge** | `--onyx` bg, white text, radius 8px, `--fs-8`, small padding |
| **Section title** | `.h3` (`--white-2`) + 30px `--text-gradient-purple` underline via `::after` |
| **Separator** | full-width 1px `--jet` line, 16–32px vertical margin |
| **Nav link** | `--light-gray`, `--fs-8`; active → `--purp-one` |
| **Timeline item** | left rail in `--jet`, purple gradient dot, dates in `--purp-two` |
| **Modal** | `--eerie-black-2` card over blurred 80% black overlay, scale-in |

---

## 10. Quick-Start Checklist for a New Site

To make a new site feel like part of this family:

1. Copy the `:root` custom properties block (colors, type, shadows, transitions).
2. Set `body { background: var(--smoky-black); }` and load **Poppins**.
3. Build every container as an `--eerie-black-2` card with a `--jet` border and
   `20px` radius.
4. Use **purple only** for interactive/active/important elements.
5. Headings `--white-2`; body text `--light-gray` at weight 300, line-height 1.6.
6. Round everything; lift with soft, low-opacity shadows.
7. Use Ionicons (outline) in gradient-bordered icon boxes.
8. Keep transitions short (0.25s) and reveals smooth (0.5s).
9. Make it mobile-first; relocate navigation and expand columns at breakpoints.
10. Match the section-title underline and gradient-border `::before` trick for
    instant visual kinship.
