---
description: Shadow tokens — primitive and semantic shadows for elevation hierarchy
---

# Shadow Tokens

## Documentation scope

**Portable across platforms:** Elevation **tier names** (`xs` … `2xl`), semantic aliases (`shadow-card`, `shadow-modal`, …), and rule “use semantic shadow tokens, not ad-hoc blur stacks”. Values are defined for light theme in tables; dark/elevated remaps live in `tokens.css` — Flutter themes should **mirror** those remaps per brightness.

**Web-specific in this file:** Raw `box-shadow` strings as carried in CSS variables. On Flutter, express with `BoxShadow` lists sourced from the same semantic level.

## Tiered Shadow Scale (Primitive)

| Token | Light | Use Case |
|-------|-------|----------|
| `--shadow-xs` | `0 1px 2px rgba(0,0,0,0.04)` | Subtle depth |
| `--shadow-sm` | `0 1px 4px rgba(0,0,0,0.06)` | Light elevation |
| `--shadow-md` | `0 2px 8px rgba(0,0,0,0.06)` | Medium elevation |
| `--shadow-lg` | `0px 2px 16px 4px rgba(0,0,0,0.04)` | Cards, dropdowns |
| `--shadow-xl` | `0 4px 24px rgba(0,0,0,0.10)` | Modals, dialogs |
| `--shadow-2xl` | `0 8px 32px rgba(0,0,0,0.14)` | Maximum elevation |

## Semantic Shadow Aliases

| Token | Maps to | Use Case |
|-------|---------|----------|
| `--shadow-card` | `--shadow-lg` | Elevated cards |
| `--shadow-dropdown` | `--shadow-lg` | Dropdown menus, popovers |
| `--shadow-modal` | `--shadow-xl` | Modals, dialogs |
| `--shadow-subtle` | `--shadow-xs` | Small element depth |

## Component Shadows

| Token | Light | Dark | Used by |
|-------|-------|------|---------|
| `--shadow-btn-inner` | `inset 0 1px 2px rgba(255,255,255,0.28)` | `inset 0 1px 2px rgba(255,255,255,0.15)` | Primary, secondary buttons |
| `--shadow-btn-hover` | `0 4px 8px rgba(0,0,0,0.08)` | `0 4px 8px rgba(0,0,0,0.3)` | Button hover |
| `--shadow-btn-secondary-hover` | `inset 0 2px 4px rgba(255,255,255,0.48)` | `inset 0 2px 4px rgba(0,0,0,0.2)` | Secondary hover |
| `--shadow-focus-ring` | `0 0 0 3px var(--color-primary-ring)` | same | All focusable elements |

> **Dark mode note:** Shadows are heavier in dark theme to remain visible on dark surfaces. `--shadow-border` also adapts: `0 0 0 1px rgba(255,255,255,0.06)` in dark.

## Badge Gradient Pattern

Solid badges use a vertical gradient fill with a solid border — no shadows:

```css
background: linear-gradient(0deg, var(--color-badge-{color}-gradient-from), var(--color-badge-{color}-gradient-to));
border: 1px solid var(--color-badge-{color}-border);
```

Counter badges follow the same pattern with their own token set (`--color-counter-{color}-*`).

## Rules

- Shadows are heavier in dark mode to remain visible on dark surfaces
- Prefer `box-shadow` over `border` for hairline edges
- Never use harsh drop shadows — keep them diffused
