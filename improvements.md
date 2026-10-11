# RAGDAMAXING: Improvements Roadmap

**Positioning:** competitive on the outside, brutal selfish self-improvement on the inside. Ragdamaxing = grindmaxing: the more you grind, the more the game pays you. Production app that makes people say "this looks great".
**Window:** ~5 months (150 days) until exams. Everything below is calibrated to what a human can actually do in that span.
**Constraints:** stdlib-only Python + SQLite, vanilla JS, no build step. The VPS auto-pulls from GitHub every 5 min and only rolls back on a Python syntax error, so front-end JS bugs go live unchecked. Test before pushing.

---

## 1. XP economy recalibration (do this first, everything else hangs on it)

### 1.1 What the code does today (server.py)
- `XP_PER_MIN = 2` for verified minutes (manual = half).
- Session milestones stack (25 min +40, 50 +100, 90 +220, 120 +400, 180 +800, 240 +1600) + clean run +20.
- Day milestones (verified min in a day): 1h +50, 2h +120, 4h +300, 6h +600, 8h +1200. **Nothing past 8h.**
- Side XP (chapters, plans, habits, quests...) capped at `SIDE_CAP = 200`/day. Good: grind decides the board.
- Level = `floor(sqrt(xp/60)) + 1`; RANKS top out at Lv 55 = 174,960 XP.

### 1.2 Problems found
1. **The title ladder is saturated.** A 90-min-block grinder doing just 3h/day makes ~1,290 XP/day = 193,500 XP in 150 days, which is already past the top title (174,960). Everyone serious ends up "RAGDAMAXED GOD". No difference between 3h/day and 16h/day.
2. **No reward past 8h/day.** The day milestones stop at 480 min, so 8h and 14h look the same on milestones.
3. **Long unbroken blocks pay far more per hour than Pomodoro.** XP/hour: 25-min pomodoro blocks ~264, 50-min ~312, 90-min ~373, 2h ~510, 4h stopwatch session ~915 (3,660 XP per 4h block). Pomodoro users earn about 1/3.5 of a marathon user for the same hours. Either credit a finished Pomodoro plan as one continuous block (a 2h plan counts as a 120-min block) or accept the bias knowingly.

### 1.3 Calibration model
Reference grinder: 90-min clean blocks (560 XP per block, ~373 XP/h) + day milestones. Proposed extra day milestones: **10h +1,500, 12h +2,500**.

| Avg verified h/day | XP per day | XP per week | XP over 150 days |
|---|---|---|---|
| 1h | 423 | 2,961 | 63,450 |
| 2h | 917 | 6,419 | 137,550 |
| 3h | 1,290 | 9,030 | 193,500 |
| 4h | 1,963 | 13,741 | 294,450 |
| 6h | 3,310 | 23,170 | 496,500 |
| 8h | 5,257 | 36,799 | 788,550 |
| 10h | 7,503 | 52,521 | 1,125,450 |
| 12h | 10,750 | 75,250 | 1,612,500 |
| 14h | 11,497 | 80,479 | 1,724,550 |
| 16h | 12,243 | 85,701 | 1,836,450 |

Add roughly +25,000 over 150 days for side XP (cap 200/day), streak bonuses and badges.

**16h/day is the mathematical ceiling, not a target.** Nobody sustains 16h verified for 150 days (sleep, food, illness, mocks). 8-10h/day for months is already elite. So the ladder's final tier is the ceiling (shown as the Everest), and the **realistic apex is Phantom (~10h/day)**.

### 1.4 New level curve
`level = floor(sqrt(xp / 190)) + 1`. Lv 100 = 1,862,190 XP = the 16h/day ceiling.
Levels are derived from XP, so no data migration, but **everyone's displayed level will drop**. Announce it to the crew before pushing.

### 1.5 New title ladder (by level, with the grind it represents)
| # | Title | Lv | XP needed | Sustained grind for 150 days |
|---|---|---|---|---|
| 1 | Sleepwalker | 1 | 0 | where everyone starts |
| 2 | Spark | 5 | 3,040 | first week back |
| 3 | Grinder | 12 | 22,990 | ~30 min/day |
| 4 | Locked In | 20 | 68,590 | ~1h/day |
| 5 | Iron Habit | 28 | 138,510 | ~2h/day |
| 6 | Night Blade | 35 | 219,640 | ~3h/day |
| 7 | Warlord | 42 | 319,390 | ~4h/day |
| 8 | Rank Reaper | 53 | 513,760 | ~6h/day |
| 9 | Apex | 66 | 802,750 | ~8h/day |
| 10 | Phantom | 78 | 1,126,510 | ~10h/day (realistic apex) |
| 11 | Titan | 92 | 1,573,390 | ~12h/day |
| 12 | RAGDAMAXED | 100 | 1,862,190 | ~16h/day, the ceiling |

Sanity check: ~1.7h/day (crew average) lands around Iron Habit. A 5.6h/day pace (your last 4 days) lands at ~Lv 47, between Warlord and Rank Reaper by exam time.

### 1.6 Weekly league tiers (the board people look at every day)
Based on weekly grind XP: Bronze <3k, **Silver 3k** (~1h/day), **Gold 9k** (~3h/day), **Platinum 23k** (~6h/day), **Diamond 37k** (~8h/day), **Apex 52k** (~10h/day). Show the tier next to your name all week and a progress bar to the next tier.

### 1.7 Pomodoro fix + milestones
- Decide the Pomodoro vs stopwatch bias (see 1.2.3).
- Add day milestones 10h/12h (1.3).
- Keep side XP capped. Keep the leaderboard on grind XP only.

---

## 2. Titles & badges rewrite

Badge rarity: Common / Rare / Epic / Legendary / Mythic. XP reward per rarity: **100 / 300 / 800 / 2,000 / 5,000** (badge XP is not capped, not grind). Show global rarity on each badge ("held by 3 of 13"). Some are secret (shown as "???" until earned).

**Hours (lifetime verified)**
- First Blood [C]: first session
- Warm-Up [C]: 10h
- Ignition [C]: 50h
- Triple Digits [R]: 100h
- Quarter Grand [R]: 250h
- Half-K Club [E]: 500h
- The Thousand [L]: 1,000h (6.7h/day average)
- Unholy Hours [M]: 1,500h (10h/day average)

**One day**
- Full Tank [C]: 4h
- Eight-Hour Shift [R]: 8h
- Overtime Demon [E]: 10h
- Sleep Is Optional [L]: 12h
- The Singularity [M, secret]: 14h

**One sitting**
- Hour of Power [C]: 60 min
- Marathoner [R]: 2h
- Ragda Beast [E]: 3h
- Unbroken [L]: 4h (the stopwatch cap)

**One week**
- Full-Time Grind [R]: 35h
- Overtime [E]: 56h
- Two Jobs [L]: 70h
- Machine [M]: 84h

**Streaks**
- Hat-Trick [C]: 3 days
- Seven Seals [C]: 7
- Fortnight Fury [R]: 14
- Unbreakable [E]: 30
- Diamond Chain [L]: 60
- Centurion [L]: 100
- Never Broke [M]: 150 (the whole window)

**Deep blocks (50+ min)**
- Deep Diver [C]: 10
- Ocean Mind [R]: 50
- Abyss Walker [E]: 150
- Leviathan [L]: 400

**Time of day**
- Dawn Patrol [C]: 5 sessions before 7 AM
- Night Shift [R]: 15 sessions started 10 PM to 3 AM
- Sunrise Cult [E]: 30 sessions before 7 AM

**Study**
- Page Turner [C]: 10 chapters learned
- Half the Map [R]: 37 learned
- Syllabus Cleared [E]: all 73 core chapters learned
- Grandmaster [L]: all mastered
- Memory Forge [C]: 25 revisions
- Recall Machine [R]: 100
- Elephant Brain [E]: 300
- Test Pilot [C]: 5 tests
- Exam Hardened [R]: 15 tests
- Glow-Up [E]: +20 points from first to latest test (min 5 tests)

**Discipline**
- Urge Slayer [C]: 10 urges beaten
- Monk Mode [R]: 50
- Self-Aware [C]: 7 reflections
- Inner Auditor [R]: 30
- Never Twice [C]: bounce back after a miss
- Phoenix [R]: 3 comebacks
- Navigator [C]: first weekly review
- Zero Hesitation [R]: median think-to-do under 2 min for a week
- Instant Ignition [E]: under 60 s

**Competitive**
- Duelist [C]: win a duel
- Undefeated [R]: 5 duel wins
- Boss Slayer [R]: part of 10 boss defeats
- Usurper [R]: take #1 from someone
- Crowned [R]: win a weekly crown
- Dynasty [E]: 3 crowns
- Podium [R]: top 3 in a season
- Most Improved [E]: category win in a season
- Season Champion [L]: #1 in a season
- Founder [L]: one of the first 13 users (never earnable again)
- Season 0 Veteran [R]: keep
- Outgrown [E]: 7-day average beats your old A+ baseline (the old "Ragdamaxed" badge, renamed so the title keeps the name)
- Completionist [M, secret]: every other badge

---

## 3. Profiles

Tap any member (leaderboard row, feed item, chat avatar) to open their profile. Same-crew only.

**Header:** avatar with tier frame, name, title + Lv (and prestige stars later), identity line ("I am becoming..."), crew rank, weekly league tier, live status.

**Trophy shelf:** every badge earned (rarity color, date earned), 3 pinned "showcase" badges the owner picks, season titles and weekly crowns, records currently held.

**Stats:** lifetime hours, XP, current + longest streak, best day, best session, deep blocks, floor days, think-to-do median.

**Graphs:** 12-week heatmap, last 8 weeks of hours, subject split.

**Competitive:** duel record (W-L), head-to-head compare button (my numbers vs theirs side by side), recent activity feed.

**Private, never shown to others:** DMs, reflections, mood/energy, urge triggers, test scores. (Optional per-user toggle to share test scores.)

**Tech:** `GET /api/profile?uid=` (same crew check), new columns `users.showcase` (JSON of 3 badge ids). Reuse `get_stats`, `level_info`, `day_stats`.

---

## 4. Ego & status system (what you're fighting for)

No real prizes. The reward is status, visibility and always knowing where you stand.

- **Always-visible standing** at the top of Today: `#4 of 13 · 220 XP behind Kritarth`. Rank-change events: "X overtook you", "You passed Y". Daily recap: "You dropped 1 place" / "You climbed 2". Rank history graph.
- **Throne:** the weekly leader holds the Crown, shown next to their name everywhere. The champion sees "X is 90 XP behind you, defend it". Challengers get an alert when within reach.
- **Prestige:** after Lv 100, "Ascend" resets XP for a permanent star beside your name. The ladder never ends.
- **Race the legend:** ghost race against the reigning champion's best week, not just your own.
- **Flex items for winners:** titles that stay, avatar frames (tier-based, gold crown frame for the champion, ember for 30-day streaks), name color/gradient from Night Blade up, unlockable app themes by rank, trophy shelf (see 3).
- **Pressure below the line:** show the closable gap ("140 XP from passing Kritarth, one deep block"). Time-limited tags like "Chasing" that clear when you move up. No permanent shame labels: those make people leave instead of fight.
- **Comeback rewards:** biggest climber of the week gets a title, so rising is also a way to win.

---

## 5. Seasons

4-week seasons (about 5 fit before exams). Winners get massive XP so everyone fights for it.

- Prizes: **#1 +30,000 / #2 +15,000 / #3 +8,000 XP**, category winners (Most Hours, Most Improved vs own previous season, Iron Streak, Deep Diver, Early Bird) **+5,000 each**.
- Eligibility to stop farming: at least 40 verified hours and 14 floor days in the season.
- Size check: 30k is about one month of a 2.5h/day grinder, roughly +8 to +10 levels mid-ladder. Winning every season (150k) is ~8% of the ceiling, so seasons can't hand out the top title alone.
- Key prefix `season:` (not grind, not capped, doesn't touch the weekly board).
- Permanent "Season N Champion" title/frame, hall of fame on the Crew tab, season standings + days left visible on Today.

---

## 6. Think-to-Do clock (time-to-start)

Measures the gap between opening the app and starting a focus block. Opening the app means intent to study, so the gap is pure "thinking instead of doing".

- Client records `opened_at` when the app becomes visible; server pairs it with the next timer start. `think_to_do = first_timer_start - opened_at`.
- Honesty rules: reset if hidden/idle >30 min; only count opens that lead to a block within 60 min; cap samples at 60 min; use the median.
- Show it after the fact, not as a live counter (a live clock = anxiety, not action).
- Surfaces: Me/profile: median this week vs last week, daily trend, fastest start ever. Badges: Zero Hesitation, Instant Ignition.
- Possible small XP hook: start within 2 min of opening = "No hesitation" bonus (side XP).
- Needs table `app_opens(user_id, day, opened_at, started_at)` + `POST /api/open`.

---

## 7. Me vs Me leaderboard

A board where the only opponent is your past self.

- Rank your own weeks by hours, floor days, deep blocks, think-to-do. "This week is your #3 best of 12."
- Columns: this week / last week / personal best week / 4-week average.
- Personal records with dates (longest session, biggest day, fastest start, longest streak).
- Extends the existing ghost-race chart. Everyone gets a way to win even when not top of the crew.

---

## 8. Weekly report

Auto-generated every Monday (covers the week just finished), shareable to the crew feed / Discord.

- Hours vs last week, floor days, best day, longest block, XP + league tier change.
- Subject split, chapters learned, revisions cleared, test trend.
- Think-to-do median, execution score (promises kept / made).
- Crew rank change and XP gap to the next person.
- One honest data-driven line ("You start 40% later on weekdays").

---

## 9. Trust (anti-cheat that doesn't cost focus)

Problem: start the stopwatch, walk away, collect up to 4h of verified XP (worth 3,660 XP per block now, so cheating pays more than ever).

- **Heartbeat** (not a bet): while a block runs, the page silently pings the server every ~60 s. You do nothing, you see nothing, zero attention cost. If pings stop >5 min (tab closed, phone locked, app killed), the session is capped at the last ping. Small gaps are forgiven.
- **Wake Lock** in focus mode so the phone screen doesn't sleep and kill the pings.
- **Passive distraction detection:** `visibilitychange`, leaving the app during a block auto-counts as a distraction.
- **Fallbacks:** one optional "still studying?" tap at the 2h mark only (no random popups). Admin flag for accounts with many max-length sessions.
- **Season prizes make this urgent:** ship the heartbeat before seasons.

---

## 10. Personal growth visuals

All inline SVG (no libraries). Existing helpers: `bars()`, `lines()`, heatmap.

- Weekly hours area chart with a 4-week moving average.
- Focus heatmap: day of week x hour of day (your real prime time).
- Subject balance as radial rings / radar.
- Burn-up chart: chapters learned vs the line needed before exam day.
- XP/level progress timeline with title milestones marked.
- Pace projection: "at this pace you reach Warlord on exam day. Need 5.1h/day for Rank Reaper".
- Think-to-do trend (should fall over time), rank history, session length distribution.
- Mood/energy vs focus correlation.
- Ragda meter as an animated gauge.
- "Then vs now" card: first week vs latest week side by side.
- Streak timeline with freezes and breaks, test score trend per subject.

---

## 11. UI / UX

Current base (minimal dark, SVG icons, token system) is solid. Goal: premium feel, instant feedback, clear hierarchy, status everywhere.

**Identity & polish**
- Replace emoji rank/badge icons with custom SVG emblems (chevron/shield system) for the 12 tiers and badges, with rarity-colored glow. Keep emoji only in feed text. This is the biggest "not childish" win.
- Rarity color tokens (Common grey, Rare blue, Epic purple, Legendary gold, Mythic red-white) used everywhere consistently.
- One display font for big numbers (self-hosted woff2, no CDN), system stack for body.
- Tier frames on avatars, name gradients for high tiers.

**Motion & feedback**
- XP count-up, progress bars that ease, rank-row reorder animation on the leaderboard (FLIP) so overtakes are visible.
- Level-up / new-title full-screen ceremony with emblem reveal. Haptics (`navigator.vibrate`) on milestones, with a settings toggle for sound/haptics.
- Optimistic UI for habit/plan toggles so taps feel instant. Skeleton loaders instead of blank flashes.
- Respect `prefers-reduced-motion`.

**Today**
- One hero "Do this now" card (picks subject + block length) so there's no decision.
- Standing strip: rank, XP gap to next place, league tier progress.
- Day-milestone track (1h / 2h / 4h / 6h / 8h) with "next: 4h, +300 XP".
- Streak-at-risk countdown ("3h 12m left to save your streak").
- During a block: live "XP banked" counter, "next milestone: 50 min, +100 XP", crew avatars currently locked in.

**Focus mode**
- OLED-black ambient mode, milestone pulse at 25 / 50 / 90 / 120 min.
- End-of-session summary card: XP breakdown, milestone hit, vs your average session, rank change. One-tap share to the feed.

**Crew / leaderboard**
- Podium hero for the top 3, sticky "you" row, rank deltas (up/down arrows vs yesterday), tier promotions.
- Tap a row to open the profile sheet; head-to-head compare sheet.

**Share cards**
- Canvas-generated stat card (title, Lv, hours, streak, rank) for WhatsApp/Instagram stories. Free growth: friends see it and join.

**Navigation & structure**
- Consistent bottom sheets, undo toasts instead of `confirm()`/`prompt()` (still used in admin PIN reset and deletes), pull-to-refresh.
- Better empty states with a next step.

**Onboarding & login**
- 3-step onboarding with a pace calculator ("142 days left. At 4h/day you finish as Warlord"), guided first 5-minute session within 60 seconds, one screen explaining XP and ranks.
- Login screen with live social proof ("13 grinders, 152h this week") and join-by-link (`/join/CODE`).

**PWA / performance**
- Service worker for offline shell and instant load; PNG icons (192/512, maskable, apple-touch-icon); splash and theme color.
- Patch DOM instead of replacing `innerHTML` on every poll to stop flicker. Replace the 25 s polling with the long-poll already used by chat for presence.

**Accessibility**
- 44 px tap targets, visible focus rings, aria labels on icon buttons, contrast pass, font scaling.

---

## 12. Production hygiene

- CI (GitHub Action): `test_api.py` + `node --check static/app.js` on every push. Deploy from a `release` branch merged only when green.
- Tests for boss battle, XP economy constants, seasons, think-to-do, profiles (crew isolation!).
- Self-serve change PIN, session expiry, 6+ char minimum, leave crew, delete account.
- Admin: error log table, retention view (inactive 3+ days).
- Later: real push notifications (Web Push breaks stdlib-only) or a Discord/Telegram nudge bot.

---

## Suggested build order

1. CI + tests (protects the 13 users)
2. XP recalibration (1) + new titles/badges (2) + level-curve announcement
3. Heartbeat + passive distraction (9), before any big prizes exist
4. Profiles (3) + standing strip + rank-change events (4)
5. Think-to-do (6) + Me vs Me (7)
6. UI/UX pass (11): SVG emblems, motion, Today hero, crew podium
7. Weekly report (8) + share cards
8. Seasons + prestige + cosmetics (5, 4)
9. Graph pack (10), growing alongside each step
