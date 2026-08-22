# What's Actually Good To Buy Second-Hand (India, 2026)

**Author:** (Laraib) — research brief, grounded in 4 independent sources
**Purpose:** Decide which categories the deal-hunter should *prioritize*, and what a "good deal"
should mean per category. This informs the depreciation model + the marketplace `category` UI.

---

## 1. The consensus (from r/buildapc, XDA, Quora, YouTube, FB groups)

Used-market reliability tiers for PC components:

| Category | Safe to buy used? | Good value? | Why |
|---|---|---|---|
| **CPU** | ✅ Strongest | ✅ Excellent | Most reliable component; no moving parts; hard to kill; almost always a good buy used |
| **RAM** | ✅ Strong | ✅ Good–holding | No moving parts; lifetime-ish; but *"anything with RAM is an appreciating asset"* in the 2026–26 memory crunch → prices may be high, buy only vs. new |
| **GPU** | ⚠️ Conditional | ✅ Good if tested | Highest ritual risk (ex-mining, VRAM/thermal wear, bathtub-curve). **Buy used ONLY if** the price gap vs. new is meaningful (>20-30%) AND you can stress-test on the spot |
| **Monitor** | ✅ Fair | ✅ Good | No moving parts; cheap-to-ship risk; lots of used inventory |
| **SSD (SATA/NVMe)** | ⚠️ Mixed | 🟡 OK | Check health/`SMART`; NVMe Gen5 holds value; no mechanical wear (unlike HDD) |
| **Motherboard** | ⚠️ Mixed | 🟡 OK | Riskier (capacitors/VRM wear, I/O failure); test thoroughly; check socket compatibility |
| **PSU** | ❌ Avoid | ❌ | **Universal "buy new"** — an aging/failing PSU can kill the whole build. Cheap insurance to buy new. |
| **HDD / mechanical** | ❌ Avoid | ❌ | Moving parts + no SMART confidence cheaply; not worth used |
| **AIO / liquid cooler** | ❌ Avoid | ❌ | Pump failure risk, no practical test |

**The two "almost-free-money" buys:** **CPU** and **RAM**.
**The "buy new always" shortlist:** **PSU**, **HDD**, **AIO cooler**.

---

## 2. GPU nuance (the highest-stakes, highest-return category)

From Tom's Hardware GPU-pricing tracking + HN's "used GPU cluster" thread:

- **Sweet spot = high-VRAM cards that are one generation old.** VRAM is the appreciating asset in
  2026 (LLM/inference demand). Buying a used **RTX 3080 10GB/3090 24GB, RX 6800 XT 16GB /
  6900 XT / 7800 XT 16GB** at a good discount gives you *today's* memory-hungry workloads cheaply.
  These hold resale value because RAM supply is constrained.
- **Red flags to program into the risk model:**
  - Ex-mining cards (the classic worry) — but note: *"the bathtub curve keeps you pretty safe if
    they weren't literally on fire when pulled"*. Mining ≠ automatically bad; **untested/undervolted
    + no-warranty + huge VRAM = scrutinize harder**.
  - **Don't overpay for "a good model"** — consumer cards are factory-overclocked; a year-old
    mid-range HR used at MSRP-ish is a bad deal vs. a newer used card for the same money.
  - **Stale "too good to be true" listing** = likely scam (already in the risk model).
- **Buy only when the discount is meaningful:** used GPU worth it when ≥20-30% below its new
  street price, because you eat the no-warranty risk.

---

## 3. What this means for the deal-hunter (implementation implications)

1. **Priority categories in the marketplace UI:** rank `cpu` and `ram` first (safe + good value),
   `gpu` prominently (high returns, needs the most risk scrutiny), `monitor`/`ssd` next, and
   **de-emphasize or hide `psu`/`hdd`/`aiocooler` used listings** or flag them "buy new" advice.
2. **Per-category depreciation should differ** (already does in `pricing.py`, but validate):
   - CPU/RAM: very slow decay, floor high.
   - GPU: faster, but **high-VRAM cards should decay slower** than low-VRAM (VRAM scarcity).
   - PSU/HDD/AIO: raise the risk weight heavily, don't recommend.
3. **"Is this a good deal" thresholds per category:**
   - CPU: ~≥15% below new = good.
   - GPU: **≥20-30% below new street price** = good enough to accept no-warranty risk.
   - RAM: only good if it clears the memory-crunch premium vs. buying new (else pointless).
   - Monitor/SSD: ~≥20% below new = good.
4. **Risk-model additions** from this research (fold into `red_flags.py`/`risk.py`):
   - Flag `psu`/`hdd`/`aio` used listings as "buy-new-recommended" (low-value used).
   - For GPUs with `vram_gb >= 16`: if price is *too* low *and* listing is stale → escalate scam
     risk (high-VRAM cards are scarce, so huge discounts on them are a stronger scam tell).
   - Detect "untested / no warranty / as-is" language → weight against for GPU.
5. **New inventory to watch for** (good/undervalued used buys to target):
   - ex-corporate / ex-datacenter CPUs (high-core Zen3/Zen4, Xeon/Epyc) — great used value.
   - 1-gen-old **high-VRAM** GPUs (RTX 3090/3080/6800XT/7800XT/6900XT).
   - Quality used Panels (1440p/165Hz monitors) — cheap now.

---

## 4. Suggested next step
Fold these per-category "good deal" thresholds + buy-new-recommended flags into the
`hardware-scale-up.md` plan (as `category_advice`) so the marketplace/scorer actually encode this
wisdom, not just search. That's a small addition to the existing catalog-scoring plan.