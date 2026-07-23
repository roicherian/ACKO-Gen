---
description: Animation tokens — easing curves, keyframes, and performance rules
---

# Motion Tokens

## Documentation scope

**Portable across platforms:** Duration and easing **intent** (what each curve is for), performance rules (prefer transform/opacity), and “when to animate” guidance. Cubic-bezier values are **portable** — use the same curves in Flutter (`Cubic` / `Curves` approximations or exact values).

**Web-specific in this file:** `@keyframes`, `animation` shorthand, `prefers-reduced-motion` CSS snippets. Mirror reduced-motion in Flutter with `MediaQuery.disableAnimations` / system settings where appropriate.

## Easing Curves

These are defined as CSS custom properties in `tokens.css`:

| Token | Value | Use |
|-------|-------|-----|
| `--ease-out-quad` | `cubic-bezier(0.25, 0.46, 0.45, 0.94)` | Standard exit |
| `--ease-out-cubic` | `cubic-bezier(0.215, 0.61, 0.355, 1)` | Dropdown/modal enter |
| `--ease-out-quart` | `cubic-bezier(0.165, 0.84, 0.44, 1)` | Strong deceleration |
| `--ease-in-out-cubic` | `cubic-bezier(0.645, 0.045, 0.355, 1)` | On-screen movement |
| `--ease-in-out-quart` | `cubic-bezier(0.77, 0, 0.175, 1)` | Emphatic transitions |

### Decision guide

| Scenario | Easing |
|----------|--------|
| Element entering/exiting | `ease-out` |
| On-screen movement | `ease-in-out` |
| Hover/color transitions | `ease` (CSS default) |
| Seen 100+ times daily | Don't animate |

## Duration

There are no `--duration-*` tokens in `tokens.css`. Use raw values (e.g. `150ms`, `200ms`, `300ms`) or define local variables in component CSS as needed.

## Shared Keyframes

Define these in the component CSS files that need them:

### `@keyframes acko-spin`
```css
@keyframes acko-spin { to { transform: rotate(360deg); } }
```
Used by: Button (loading spinner). Duration: 600ms linear infinite.

### `@keyframes acko-shake`
```css
@keyframes acko-shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-4px); }
  40% { transform: translateX(4px); }
  60% { transform: translateX(-3px); }
  80% { transform: translateX(2px); }
}
```
Used by: TextInput (error), Dropdown (error). Duration: 300ms ease-out.

### `@keyframes acko-check-pop`
```css
@keyframes acko-check-pop {
  0% { opacity: 0; transform: scale(0.5); }
  60% { opacity: 1; transform: scale(1.15); }
  100% { opacity: 1; transform: scale(1); }
}
```
Used by: TextInput (success). Duration: 300ms ease-out.

### `@keyframes acko-menu-enter`
```css
@keyframes acko-menu-enter {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: translateY(0); }
}
```
Used by: Dropdown menu. Duration: 150ms ease-out-cubic.

### `@keyframes acko-tick-pop`
```css
@keyframes acko-tick-pop {
  0% { opacity: 0; transform: scale(0.3); }
  60% { opacity: 1; transform: scale(1.15); }
  100% { opacity: 1; transform: scale(1); }
}
```
Used by: Dropdown (selected item tick). Duration: 250ms ease-out.

## Performance Rules

- Only animate `transform` and `opacity` (GPU-accelerated)
- Never animate `padding`, `margin`, `height`, `width`
- Use `will-change: transform` for frequently animated elements
- Exit animations 20–30% faster than entrances
- Respect `prefers-reduced-motion`

Motion tokens are **theme-agnostic**.
