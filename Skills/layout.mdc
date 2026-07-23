---
description: Layout system — breakpoints, section containers, full-bleed sections, gutters, grid rules, and desktop scaling
alwaysApply: true
---

# Layout System

Structural layout primitives: width, containment, gutters, full-bleed, and desktop scaling.
All pages and sections must adhere to this system unless explicitly overridden by a component specification.

## Documentation scope

**Portable across platforms:** breakpoint *cutoffs* (767 / 768 / 1024), gutter *values* (16 / 32 / 40px), max content width (1280px cap), “typography-only scaling between 1024–1280px”, full-bleed *pattern* (outer edge-to-edge + inner constrained content), and grid discipline (no fixed column px, avoid `100vw` in nested layout).

**Web-specific in this file:** CSS snippets, class names (`section-container`, `full-bleed`), and Tailwind utilities (`p-16`, `p-32`, `p-40`). On Flutter, express the same numbers via padding/theme; use `LayoutBuilder` / breakpoints packages as appropriate — the *gutter and width intent* stays the same.

## Breakpoints

Mobile-first only. Use `min-width` media queries exclusively. **Never** mix with `max-width`.

| Name | Range | Media Query |
|------|-------|-------------|
| Mobile | 0 – 767px | Base styles (no media query) |
| Tablet | 768px – 1023px | `@media (min-width: 768px) { }` |
| Desktop | 1024px and above | `@media (min-width: 1024px) { }` |

Mobile styles are the default. Tablet overrides at 768px. Desktop overrides at 1024px.

A device at exactly 768px receives Tablet styles. A device at exactly 1024px receives Desktop styles.

## Section Container (Default)

The standard constrained wrapper used in most sections. Controls maximum readable width, horizontal gutters, and center alignment.

### CSS

```css
.section-container {
  width: 100%;
  padding-left: 16px;   /* 16px — mobile */
  padding-right: 16px;
}

@media (min-width: 768px) {
  .section-container {
    padding-left: 32px;  /* 32px — tablet */
    padding-right: 32px;
  }
}

@media (min-width: 1024px) {
  .section-container {
    max-width: 1280px;
    margin: 0 auto;
    padding-left: 40px;  /* 40px — desktop */
    padding-right: 40px;
  }
}
```

### Effective Content Width (Desktop)

| Viewport | Container | Usable Content |
|----------|-----------|----------------|
| 1024px | 1024px (fluid) | 944px |
| 1280px | 1280px (capped) | 1200px |
| > 1280px | 1280px (centered) | 1200px |

Content must never touch viewport edges at desktop widths.

### Gutters

| Breakpoint | Gutter | Token |
|------------|--------|-------|
| Mobile | 16px | `p-16` |
| Tablet | 32px | `p-32` |
| Desktop | 40px | `p-40` |

Gutters are **internal padding**, not margin. This preserves structural alignment, maintains predictable grid calculations, prevents layout shift in nested contexts, and keeps full-bleed behavior consistent.

## Full-bleed Sections

Used for hero banners, image/video/animation backgrounds (Lottie / JSON-based), visual storytelling blocks, and edge-to-edge media.

Full-bleed sections must span the full viewport width on all devices.

### Required Two-layer Structure

```html
<!-- Outer: spans full viewport width (background/media edge-to-edge) -->
<section class="full-bleed">
  <!-- Inner: constrains content using Section Container rules -->
  <div class="section-container">
    ...content...
  </div>
</section>
```

```css
.full-bleed {
  width: 100%;
}
```

The outer wrapper carries the background/image/video/animation. The inner content uses Section Container rules for alignment. This ensures visual immersion, structural consistency, and aligned content across all sections.

## Desktop Typography Scaling

Between **1024px and 1280px**, only typography scales. Grid column count, spacing, and component density remain constant.

| Viewport | Typography |
|----------|------------|
| 1024px | Minimum desktop type scale |
| 1280px | Maximum desktop type scale |
| > 1280px | No further scaling |

### Implementation

- **Preferred:** fluid scaling using `clamp()`
- **Acceptable:** stepped increase at `@media (min-width: 1280px)`

## Grid Rules

- Use relative units (`fr`, `%`) — no fixed pixel widths for layout columns
- Avoid `100vw` inside constrained containers (use `100%` relative to parent)
- Use `minmax(0, 1fr)` to prevent overflow issues
- Grid structure must not change between 1024px and 1280px

## Anti-Patterns

| Don't | Do |
|-------|----|
| `max-width` media queries | `min-width` media queries (mobile-first) |
| Margin for gutters | Padding for gutters |
| Fixed pixel column widths | `fr` / `%` / `minmax()` |
| `100vw` inside constrained containers | `100%` relative to parent |
| Scale spacing between 1024–1280px | Only scale typography |
| Skip inner container in full-bleed | Always use two-layer structure |
| Hardcoded gutter values (`padding: 16px`) | `p-16` / `p-32` / `p-40` Tailwind utilities |
| Introduce new container variants | Use Section Container or Full-bleed only |

## Non-Negotiable Rules

1. Desktop layout begins at **1024px**.
2. Section Container is fluid until 1280px, then capped and centered.
3. Desktop gutters are fixed at 40px (`p-40`).
4. Tablet gutters are 32px (`p-32`).
5. Mobile gutters are 16px (`p-16`).
6. Typography is the **only** scaling variable between 1024px and 1280px.
7. Full-bleed sections **must** use the two-layer structure.
8. No additional container variants without system-level review.
