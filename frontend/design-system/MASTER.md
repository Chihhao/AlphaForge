# AlphaForge Master Design System (v2.0)

## 1. Core Aesthetic: Compact Forge (Professional Tech/Fin)
A high-efficiency, compact, and data-centric aesthetic designed for terminal-like precision and professional trading tools.

### Key Visual Signature
- **Terminal Cursor (`_`)**: Every major header or brand text must end with a `<span className="text-emerald-400">_</span>`. 
- **Compactness**: Minimize excessive white space to maximize data visibility on a single screen.

---

## 2. Color Palette
| Role | Hex | Tailwind Class | Usage |
|------|-----|----------------|-------|
| **Background** | #101827 | `bg-brand-dark` | Deep navy-black core background |
| **Primary Accent** | #34d399 | `text-emerald-400` | Cursors, status icons (positive), logo mark |
| **Secondary Accent** | #22d3ee | `text-cyan-400` | Links, subtle highlights |
| **Text Primary** | #fafafa | `text-neutral-50` | Headers and high-contrast content |
| **Text Muted** | #a1a1aa | `text-neutral-400` | Labels, metadata, descriptions |
| **Borders** | #18181b | `border-zinc-900` | Section dividers and card outlines |

---

## 3. Spacing & Layout (The 16px Rule)
We prioritize a "Grid-Strict" approach for mobile reliability.

### Mobile (Portrait) Spacing
- **Outer Margins**: `px-4` (16px) - All content must align to this vertical grid.
- **Vertical Gaps**: `16px` (gap-4) between all functional cards/sections.
- **Search Header High-Tightness**: Inner spacing between Nav and Search is reduced to `pt-1` (4px) on mobile for maximum accessibility.

### Desktop (Large Screen) Spacing
- **Gaps**: `24px` (gap-6) between major sections for better breathing room while maintaining density.

---

## 4. Typography
- **Core Font**: IBM Plex Sans or Roboto (Clean Sans-serif).
- **Data/Numeric Font**: Any Monospace (e.g., Fira Code, IBM Plex Mono) is MANDATORY for stock IDs and prices to ensure column alignment.
- **Heading Style**:
  - H1: 2.25rem / Bold + Cursor
  - H2: 1.5rem / Semibold + Cursor
  - H3: 1.25rem / Bold

---

## 5. Components & Interaction
- **LOGO**: Using `mdi-target` (Target/Crosshair) icon in `#34d399`. **NO hover effect** (static brand identity).
- **Buttons**:
  - Primary: High contrast (Neutral-50 bg, Black text).
  - Search: Functional, monospace fonts, responsive placeholders (simplified on mobile).
- **Interactions**: Subtle color shifts for links, but maintain brand-dark stability for structural elements.

---

## 6. Favicon & Identity
- **File**: `/alphaforge/favicon.svg`
- **Format**: Vector (SVG) for perfect clarity at any scale.
- **Theme**: Emerald-400 Target.
