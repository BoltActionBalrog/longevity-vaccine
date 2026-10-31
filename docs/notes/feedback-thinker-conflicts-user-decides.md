---
name: feedback-thinker-conflicts-user-decides
description: Thinker compat rule (user 2026-10-28): ALL Thinker functionality AND all of ours must be preserved; any conflict of any kind is brought to the maintainer for an explicit decision -- never resolve a player-facing conflict by assumption
type: feedback
---

**Rule (user, 2026-10-28, verbatim intent):** in the Thinker compatibility work, all functionality of
Thinker must be preserved as well as our own. If there would ever be a conflict, bring it to the maintainer
and get an explicit decision. Never assume how to resolve a player-facing conflict between our work and
Thinker, of any kind.

**Why:** Thinker is a feature mod players chose on purpose (AI, rules, UI additions such as the 5.5
main-menu "Change Options" button, its own screen scaling for some screens). Silently dropping one of
its patches to make ours apply, or dropping ours to make its apply, changes what a player gets without
anyone deciding it. Collisions under Thinker are fatal at launch (exit_fail), so "let it skip" is not a
resolution either.

**How to apply:**
- The static overlap check reports every colliding site/group with WHAT each side does there; it never
  auto-excludes a group. Exclusion lists in `patches.yaml` targets are written only from a decision the
  user made, and the yaml comment names the decision and date.
- Screen ownership (menu strip, credits/interlude, main-menu button, fog-of-war render fix, etc.) is a
  per-screen user decision, presented with both behaviours described, including the option of keeping
  both where technically possible (chain/wrap instead of replace).
- Inert-under-Thinker items (riotfix, hudmovesfix) are still decisions: "accept inert" is the maintainer's
  call, not a default.
- Scope: only PRACX + Thinker is a shipping target (Thinker-alone is not) -- see
  [[project-smac-supported-targets]], [[project-smac-thinker-compat]].
