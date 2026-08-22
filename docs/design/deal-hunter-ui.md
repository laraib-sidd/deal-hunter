# Deal Hunter — UI/UX Design Spec & Wireframes

**Design direction:** *Linear-inspired calm-dark data console.* Precision engineering, near-black
canvas, information hierarchy via luminance gradation, a single indigo-violet interactive accent,
and a **deal-signal color system** (green/amber/red) that carries meaning — never decoration.

The product is a **price-intelligence console**, not a scraper. Every screen answers "what's a
good deal, right now, and why." The UI's job is to make the *signal* legible at a glance.

---

## 0. Design Principles (the "why" behind every decision)

1. **Signal over decoration.** Green = genuinely below market, amber = negotiable, red = scam/over.
   Color is used to communicate deal quality, nothing else.
2. **Progressive disclosure.** Overview shows signals; click a product to see the evidence
   (price history, live baseline); click a listing to go to the source offer.
3. **Luminance hierarchy, not box borders.** Content is separated by background opacity steps
   (`rgba(255,255,255, 0.02 → 0.05 → 0.08`) and whitespace, mirroring Linear — not by heavy
   visible borders.
4. **Density that breathes.** Tabular data is tight but not cramped; key numbers are large and
   calm; secondary metadata collapses to muted quaternary gray.
5. **Real-time is implied, not shouted.** "Live" states use a small pulsing dot, never a spinner.

---

## 1. Design Tokens

### Color
```css
/* Canvas */
--bg:          #0d0e0f;   /* page — near-black, slightly cool */
--panel:       #141517;   /* sidebar / card base */
--surface:     #18191b;   /* elevated card */
--surface-2:   #1e1f22;   /* hover / nested */

/* Text */
--text-1:  #f7f8f8;   /* primary — never pure white */
--text-2:  #b8bec8;   /* secondary body */
--text-3:  #8a8f98;   /* muted metadata */
--text-4:  #5b5f66;   /* quaternary — timestamps, labels */

/* Interactive accent (Linear indigo-violet) */
--accent:       #5e6ad2;
--accent-hi:    #7170ff;
--accent-hover: #828fff;

/* Deal-signal system (the ONLY semantic color) */
--deal-buy:       #27a644;  /* genuine below-market */
--deal-negotiate: #e8a33d;  /* within range, room to improve */
--deal-pass:      #e05d5d;  /* overpriced */
--deal-scam:      #ff4949;  /* red flag / scam-risk */

/* Borders — ultra-thin translucent white, per Linear */
--border:       rgba(255,255,255,0.06);
--border-soft:  rgba(255,255,255,0.04);
--border-strong:rgba(255,255,255,0.09);
```

### Typography
```
Fonts: Inter (400/510/590) + JetBrains Mono (500) for numbers
UI  : 13-14px, weight 510
Meta: 12px, weight 400, --text-4
Price/stat value: 22-26px, mono, weight 500
Headline: 20px, weight 590, letter-spacing -0.24px
```

### Radius
2px (chip) · 6px (buttons/inputs) · 8px (cards) · 12px (featured)

### Spacing
Base 8px grid: 4 / 8 / 12 / 16 / 24 / 32. Section rhythm 24px.

---

## 2. Component Library (implemented in base.html)

| Component | Spec |
|---|---|
| **Stat card** | `--surface` bg, border-soft, radius 8px, 16px padding. Label 11px uppercase `--text-4`; big value 24px mono `--text-1`; optional delta-line colored by signal (▲ below-market green / ▼ over red). |
| **Status chip** | 2px radius, 11px uppercase w/ letter-spacing, tinted bg `color@12%` + colored text. `BUY`, `NEGOTIATE`, `PASS`, `SCAM_RISK`. |
| **Source pill** | transparent bg, `--border` border, 9999px radius, 12px `--text-2`. |
| **Live dot** | 6px circle `--deal-buy` with `box-shadow: 0 0 0 3px color@20%` pulse. |
| **Table** | header 11px uppercase `--text-4`; row `--border-soft` bottom border; hover row `--surface` bg. |
| **Score bar** | 10-segment monospace block `████░░░░░░` colored by signal; numeric at right. |
| **Price delta badge** | `ArrowDown`+green if pct < -5, `ArrowUp`+red if > +5, `AtMarket`+neutral o/w. Contains `market_percentile` when available. |
| **Ghost button** | `rgba(255,255,255,0.02)` bg, `--border` border, 6px radius, 12px. |
| **Filter bar** | sticky row of ghost pills + search input — same affordance as Linear's toolbar. |

---

## 3. Screen Wireframes

### 3.1 Dashboard `/`
```
┌────────────────────────────────────────────────────────────────────────────┐
│ ◉ Deal Hunter        Dashboard   Deals   Watch        [search… ⁄]  ⌘K      │  <- top bar
├────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  GRID OF 4 STAT CARDS                                                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐            │
│  │ NEW / 24H  │ │  ACTIVE    │ │  DEALS ≥6  │ │  WATCHES    │            │
│  │  290  ▲     │ │   4,146     │ │    1  ▟    │ │     3       │            │
│  │ ███ active  │ │  – calm     │ │  green box │ │  – muted    │            │
│  └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘            │
│                                                                             │
│  ┌───────────────────────────────┐  ┌───────────────────────────────┐      │
│  │ LATEST LISTINGS          filter │  │ MARKET PULSE                │      │
│  │ ┌────────────────────────────┐ │  │  product ▓▓▓▓▓░░ worth        │      │
│  │ │ title                price│ │  │  RTX3080  ₹25k ▓▓▓▓▓▓▓░░░    │      │
│  │ │ ───────────────────────── │ │  │  Ryzen5   ₹12k ▓▓▓░░░         │      │
│  │ │ ...                     │ │  │  …bar = median, dot = this     │      │
│  │ └────────────────────────────┘ │  └───────────────────────────────┘      │
│  │                                │  │ SOURCE BREAKDOWN                │      │
│  │ table w/ chip + scorebar      │  │  ● reddit 3,502                 │      │
│  │ click title → /product/…      │  │  ○ techenclave 354              │      │
│  └───────────────────────────────┘  └───────────────────────────────┘      │
└────────────────────────────────────────────────────────────────────────────┘
```
**UX notes:** The top card grid is a "donor" for instant scannability. The right rail is the
"market pulse" — a compact equity-style listing of top products with a horizontal bar showing
where current listings sit vs median. Left table supports sorting by clicking headers.

### 3.2 Deals `/deals`
```
┌────────────────────────────────────────────────────────────────────────────┐
│ header…                                                                      │
│ ── FILTER BAR (sticky) ─────────────────────────────────────────────────┐   │
│  [search box…]  (All sources ▾) (Any verdict ▾) (Price ▾)  [Reset]     │   │
│ └───────────────────────────────────────────────────────────────────────┘   │
│  DEAL LIST (card-per-deal)                                                   │
│  ┌───────────────────────────────────────────────────────────────┐          │
│  │ [BUY]  NVIDIA RTX 3080 · 10GB     ────   ₹25,000       ▲ 18% below   │  │
│  │   techenclave · New Delhi · 3h ago     ████████░░ 8/10   Offer →    │  │
│  └───────────────────────────────────────────────────────────────┘          │
│  …                                                                           │
└────────────────────────────────────────────────────────────────────────────┘
```
**UX notes:** Card-per-deal (not dense table) because deals are a *shortlist to act on*, not a
browse dump. Big title, mono price, colored delta badge, score bar, one primary action
("Open"). Sticky filter bar.

### 3.3 Product `/product/{canonical}`
```
┌────────────────────────────────────────────────────────────────────────────┐
│ header…                                                                      │
│  NVIDIA GeForce RTX 3080        [source chips]   [watched? ★]              │
│  ┌───────────────────────────────┐                                            │
│  │ PRICE HISTORY  (60d)         │                                            │
│  │      ₹30k ─╮                  │                                            │
│  │      ₹25k ╭──╯▂▂▂▂           │   <- sparkline SVG                        │
│  │      ₹20k ─┼──┄median         │                                            │
│  │       Apr   May   Jun        │                                            │
│  └───────────────────────────────┘                                            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐  ← IV stat cards                        │
│  │Median ₹25k│ │p25 ₹22k│ │p75 ₹28k│  │n=24 obs│                              │
│  └─────────┘ └─────────┘ └─────────┘                                          │
│  CURRENT OFFERS (table)                                                        │
│   asking | source | seller | score | status | posted                           │
│  SELLER RISK STRIP                                                             │
└────────────────────────────────────────────────────────────────────────────┘
```
**UX notes:** This is the "evidence" screen — sparkline on top, live baseline stat cards, then
the offers table. Seller risk as a compact strip under the table.

### 3.4 Watch `/watch`
```
┌────────────────────────────────────────────────────────────────────────────┐
│ header…                                                                      │
│  WATCH RULES                                 [ + Add via bot ]               │
│  ┌───────────────────────────────────────┐                                    │
│  │ #3  rtx 3060 under 15k   enabled   ★  │   row-click → toggle                │
│  └───────────────────────────────────────┘                                    │
│  RECENT HITS                                                                    │
│  timestamps + linked listing ids                                               │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Empty / Loading / Error states

- **Empty data** ("No deals yet"): ghost illustration area + one-line hint + CTA button, not a
  bare "—".
- **0 scored listings**: dashboard shows a subtle amber banner "Run scoring to enable market
  analysis" with a `Run now` action.
- **Source down** (e.g. techenclave hang): source pill turns amber with a tooltip, does *not*
  break the page.
- **Live dot** animates only the first 5s after each poll; then static.

---

## 5. Accessibility & Responsive

- All signal colors also carry text + icon (never color-alone) — chip has label, delta has arrow.
- Contrast: `--text-2` on `--bg` ≥ 4.5:1.
- Tables collapse to stacked cards at <768px; filter bar wraps.
- Touch targets ≥36px.
- Keyboard: filter inputs + buttons focusable with a visible `--accent-hi` ring (Linear-style
  multi-layer focus shadow).

---

## 6. Implementation Order
1. base.html (tokens + components + top bar)
2. index.html (stat grid + latest + market pulse + sources)
3. deals.html (filter bar + deal cards)
4. product.html (sparkline + baseline + offers + seller strip)
5. watch.html (rules + hits) and new seller.html

Each step verified by curl 200 + visual browser check, then ruff + pytest.