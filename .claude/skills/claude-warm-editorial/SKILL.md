---
name: claude-warm-editorial
description: Reusable "Claude warm editorial" design system extracted from Anthropic's Claude.com — a tinted cream canvas with serif display headlines (Copernicus/Tiempos, substitute Fraunces or Cormorant Garamond), warm coral CTAs (#cc785c), and dark navy product-mockup surfaces (#181715). Warm and humanist where most AI/SaaS brands use cool blue + slate. Use when building or redesigning a website/app that should follow this look ("use the claude design", "warm editorial theme", "cream and coral theme", "claude-inspired UI").
---

# Claude Warm Editorial Design System

A warm-canvas editorial interface style modeled on Anthropic's Claude product. The system
anchors on a tinted cream canvas with serif display headlines, warm coral CTAs, and dark navy
product surfaces (code editor mockups, model showcase cards, elevated panels). Brand voltage
comes from the cream/coral pairing — deliberately warm and humanist where most AI brands use
cool blue + slate. Type voice runs a slab-serif display ("Copernicus" / Tiempos Headline,
substitute Cormorant Garamond / Fraunces / EB Garamond) for headlines and a humanist sans
(StyreneB / Inter) for body.

## Design Tokens

```yaml
colors:
  primary: "#cc785c"
  primary-active: "#a9583e"
  primary-disabled: "#e6dfd8"
  ink: "#141413"
  body: "#3d3d3a"
  body-strong: "#252523"
  muted: "#6c6a64"
  muted-soft: "#8e8b82"
  hairline: "#e6dfd8"
  hairline-soft: "#ebe6df"
  canvas: "#faf9f5"
  surface-soft: "#f5f0e8"
  surface-card: "#efe9de"
  surface-cream-strong: "#e8e0d2"
  surface-dark: "#181715"
  surface-dark-elevated: "#252320"
  surface-dark-soft: "#1f1e1b"
  on-primary: "#ffffff"
  on-dark: "#faf9f5"
  on-dark-soft: "#a09d96"
  accent-teal: "#5db8a6"
  accent-amber: "#e8a55a"
  success: "#5db872"
  warning: "#d4a017"
  error: "#c64545"

typography:
  display-xl: { fontFamily: "Copernicus, Tiempos Headline, serif", fontSize: 64px, fontWeight: 400, lineHeight: 1.05, letterSpacing: -1.5px }
  display-lg: { fontFamily: "Copernicus, Tiempos Headline, serif", fontSize: 48px, fontWeight: 400, lineHeight: 1.1, letterSpacing: -1px }
  display-md: { fontFamily: "Copernicus, Tiempos Headline, serif", fontSize: 36px, fontWeight: 400, lineHeight: 1.15, letterSpacing: -0.5px }
  display-sm: { fontFamily: "Copernicus, Tiempos Headline, serif", fontSize: 28px, fontWeight: 400, lineHeight: 1.2, letterSpacing: -0.3px }
  title-lg: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 22px, fontWeight: 500, lineHeight: 1.3, letterSpacing: 0 }
  title-md: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 18px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0 }
  title-sm: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 16px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0 }
  body-md: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 16px, fontWeight: 400, lineHeight: 1.55, letterSpacing: 0 }
  body-sm: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 14px, fontWeight: 400, lineHeight: 1.55, letterSpacing: 0 }
  caption: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 13px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0 }
  caption-uppercase: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 12px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 1.5px }
  code: { fontFamily: "JetBrains Mono, ui-monospace, monospace", fontSize: 14px, fontWeight: 400, lineHeight: 1.6, letterSpacing: 0 }
  button: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 14px, fontWeight: 500, lineHeight: 1.0, letterSpacing: 0 }
  nav-link: { fontFamily: "StyreneB, Inter, sans-serif", fontSize: 14px, fontWeight: 500, lineHeight: 1.4, letterSpacing: 0 }

rounded:
  xs: 4px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 96px

components:
  button-primary: { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.md}", padding: "12px 20px", height: 40px }
  button-primary-active: { backgroundColor: "{colors.primary-active}" }
  button-secondary: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}", rounded: "{rounded.md}", border: "1px solid {colors.hairline}" }
  button-secondary-on-dark: { backgroundColor: "{colors.surface-dark-elevated}", textColor: "{colors.on-dark}" }
  button-icon-circular: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}", rounded: "{rounded.full}", size: 36px }
  text-link: { textColor: "{colors.primary}" }
  top-nav: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}", height: 64px }
  feature-card: { backgroundColor: "{colors.surface-card}", rounded: "{rounded.lg}", padding: "{spacing.xl}" }
  product-mockup-card-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.on-dark}", rounded: "{rounded.lg}", padding: "{spacing.xl}" }
  code-window-card: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.on-dark}", rounded: "{rounded.lg}", padding: "{spacing.lg}" }
  callout-card-coral: { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.lg}", padding: "{spacing.xxl}" }
  text-input: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}", rounded: "{rounded.md}", padding: "10px 14px", height: 40px, border: "1px solid {colors.hairline}" }
  text-input-focused: { border: "1px solid {colors.primary}", ring: "3px {colors.primary} @ 15% alpha" }
  badge-pill: { backgroundColor: "{colors.surface-card}", textColor: "{colors.ink}", rounded: "{rounded.pill}", padding: "4px 12px" }
  badge-coral: { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.pill}", padding: "4px 12px" }
  category-tab-active: { backgroundColor: "{colors.surface-card}", textColor: "{colors.ink}", rounded: "{rounded.md}" }
  cta-band-coral: { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.lg}", padding: 64px }
  footer: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.on-dark-soft}", padding: 64px }
```

## Overview

Claude.com is the warmest, most editorial interface in the AI-product category. The base
atmosphere is a **tinted cream canvas** (`colors.canvas` — #faf9f5) — distinctly warm,
deliberately not the cool gray-white that every other AI brand uses. Headlines run a
**slab-serif display** at weight 400 with negative letter-spacing, paired with humanist sans
body. The combination feels like a literary publication, not a SaaS marketing page.

Brand voltage comes from the **cream + coral pairing** — coral (`colors.primary` — #cc785c) is
the signature accent, used on every primary CTA, on the brand wordmark, and on full-bleed
callout cards. The coral is warm, slightly muted, never cyan/blue.

Three surface modes alternate page-by-page:
1. **Cream canvas** (`colors.canvas`) — default body floor
2. **Light cream cards** (`colors.surface-card`) — feature card backgrounds
3. **Dark navy product surfaces** (`colors.surface-dark`) — mockup panels, pre-footer CTAs, footer

**Key characteristics:**
- Warm cream canvas with dark warm-ink text (`colors.ink` — #141413).
- Coral primary CTA used scarcely on individual buttons, generously on full-bleed coral cards.
- Slab-serif display headlines with negative letter-spacing, paired with humanist sans body.
- Dark navy product-mockup cards for data/product chrome (tables, live panels, code/status blocks).
- Light cream feature cards — one step darker than canvas.
- Border radius is hierarchical: 8px buttons/inputs, 12px content cards, 16px hero containers, pill badges.
- Elevation philosophy is **color-block first, shadow rare**. Depth comes from cream-vs-dark surface contrast, not shadows.

## Colors

- **Coral / Primary** (#cc785c): every primary CTA background, full-bleed coral callout cards, brand accent.
- **Coral Active** (#a9583e): press/hover-darker variant.
- **Coral Disabled** (#e6dfd8): desaturated cream-tinted disabled state.
- **Accent Teal** (#5db8a6): secondary product surfaces, "active" status indicators.
- **Accent Amber** (#e8a55a): companion warm tone for category badges, inline highlights.
- **Canvas** (#faf9f5): default page floor.
- **Surface Soft** (#f5f0e8): section dividers, soft band backgrounds.
- **Surface Card** (#efe9de): feature/content cards, one step darker than canvas.
- **Surface Cream Strong** (#e8e0d2): selected tabs, emphasized section bands.
- **Surface Dark** (#181715): product-mockup panels, footer.
- **Surface Dark Elevated** (#252320): elevated cards inside dark bands.
- **Surface Dark Soft** (#1f1e1b): code/data block backgrounds inside larger dark cards.
- **Hairline** (#e6dfd8) / **Hairline Soft** (#ebe6df): 1px border tones on cream surfaces.
- **Ink** (#141413): headlines and primary text.
- **Body Strong** (#252523) / **Body** (#3d3d3a): running text.
- **Muted** (#6c6a64) / **Muted Soft** (#8e8b82): secondary text, captions, fine print.
- **On Primary** (#ffffff): text on coral. **On Dark** (#faf9f5) / **On Dark Soft** (#a09d96): text on dark surfaces.
- **Success** (#5db872) / **Warning** (#d4a017) / **Error** (#c64545): semantic status.

## Typography

Slab-serif display face (Copernicus / Tiempos Headline — substitute **Cormorant Garamond**,
**Fraunces**, or **EB Garamond**) for h1–h3 and hero display, weight 400 only, negative tracking
(-0.3 to -1.5px). Humanist sans (StyreneB — substitute **Inter**) for body, nav, buttons, labels,
weight 400–500. **JetBrains Mono** for code/monospace/timestamp-style data.

Never bold the serif display weight. Never use the sans for display headlines — the serif
character is the brand voice.

## Layout

- Base spacing unit 4px: xxs 4 · xs 8 · sm 12 · md 16 · lg 24 · xl 32 · xxl 48 · section 96.
- Card internal padding: 32px for feature/content cards, 24px for compact/data cards.
- Section vertical rhythm: 96px between major bands (scale down for dense app UI).
- Max content width ~1200px centered for marketing-style layouts; app/dashboard layouts can run wider.

## Elevation & Shapes

| Level | Treatment |
|---|---|
| Flat | No shadow, no border — body sections, top nav |
| Soft hairline | 1px hairline border — inputs, sub-nav, cards |
| Cream card | `surface-card` background, no shadow |
| Dark surface card | `surface-dark` background, no shadow |
| Subtle drop shadow | Rare, low-alpha, hover-elevated states only (`0 1px 3px rgba(20,20,19,0.08)`) |

Border radius: 4px (badge accents) · 6px (small inline buttons) · 8px (CTA buttons, inputs, tabs)
· 12px (content cards) · 16px (hero/marquee containers) · pill (badges).

## Components

- **top-nav**: cream bar, 64px tall, wordmark left, menu center-left, "Sign in"-style text link + primary button right.
- **button-primary**: coral bg, white text, 8px radius, 12×20px padding, 40px height. Active → darker coral.
- **button-secondary**: cream bg, hairline border, ink text, same sizing as primary.
- **button-secondary-on-dark**: `surface-dark-elevated` bg over dark cards — never inverts to light.
- **button-icon-circular**: 36px circle, cream bg, hairline border.
- **text-link**: coral inline links, underline on press.
- **feature-card**: `surface-card` bg, 12px radius, 32px padding, icon + title + body.
- **product-mockup-card-dark**: `surface-dark` bg, 12px radius, 32px padding — for data tables, live status, product chrome.
- **code-window-card / data-window-card**: dark card with `surface-dark-soft` inner block, monospace type.
- **callout-card-coral**: full-bleed coral card, 48px padding, major CTA moments.
- **text-input / text-input-focused**: cream bg, hairline border 8px radius, 40px height; focus → coral border + 3px coral@15% ring.
- **badge-pill**: `surface-card` bg, ink text, pill radius, 4×12px padding — neutral tags.
- **badge-coral**: coral bg, white text, pill, uppercase caption type — "NEW"/featured labels.
- **category-tab / category-tab-active**: transparent/muted → `surface-card` bg + ink text when active.
- **cta-band-coral / cta-band-dark**: full-width pre-footer CTA bands, 64px padding.
- **footer**: `surface-dark` bg, `on-dark-soft` text, never inverts.

## Do's and Don'ts

**Do**
- Anchor every page on the cream canvas — never pure white.
- Use the serif display for every headline; pair with the humanist sans body. Negative letter-spacing on display sizes is non-negotiable.
- Reserve coral for primary CTAs and full-bleed callout moments — don't scatter it as a general accent.
- Use dark navy product-mockup cards to show real product/data chrome (tables, live status, logs) instead of decorative illustration.
- Pair cream feature cards with dark product cards in alternating bands for pacing.
- Apply generous section spacing; let type breathe.

**Don't**
- Don't use cool grays or pure white for canvas.
- Don't bold the serif display weight.
- Don't use cool blue or saturated cyan as a brand accent — coral is the brand voltage.
- Don't put coral everywhere — it's scarce on elements, generous only on full-bleed cards.
- Don't use the sans for display headlines.
- Don't add hover styling beyond what's encoded — primary darkens on press; that's it.

## Known Gaps / Substitutions

Copernicus and StyreneB are licensed Anthropic typefaces, not available as public web fonts.
For web implementations, use **Fraunces** or **Cormorant Garamond** (Google Fonts) as the serif
display substitute, and **Inter** (Google Fonts) as the sans substitute — both ship free and have
proportions close to the originals. **JetBrains Mono** (Google Fonts) covers monospace needs.
