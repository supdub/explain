---
name: explain
description: Build self-contained visual HTML explainers, diagrams, simulations, or slide decks and serve each on its own localhost port. Use for visual explanation requests, beginners asking to understand a topic visually, or listing, updating, and re-serving existing explainers. Answer a plain "explain X" without a visual request in chat.
---

# Explain

Resolve `scripts/explain.py` relative to this SKILL.md; use its absolute path as `S` in shell commands. Run `python3 "$S" list` before creating an explainer. Run `python3 "$S" --help` for commands: `serve`, `stop`, `list`, `check`, `shoot`.

Design each explainer for its topic and reader:

1. Store each page in `~/.explain/<slug>/index.html`, or under `$EXPLAIN_DIR` when set. Slugs start with a lowercase letter or digit, contain only `a-z0-9-`, and are at most 40 characters. Update an existing matching topic in place.
2. Keep it self-contained: inline CSS/JS/SVG or relative local assets; no CDN, web fonts, remote images, or network fetches. External source citations are fine. The page must open offline.
3. Read relevant user-provided sources and research needed claims before writing. Cite sources on the page and disclose what could not be verified.
4. Serve with `python3 "$S" serve <slug>` only. The helper detaches, binds loopback, and remembers each slug's port. Stop with `python3 "$S" stop <slug>`; do not use broad process-killing commands. Ports remain stable unless occupied by another service.
5. Run `check <slug>` and fix every FAIL. Run `shoot <slug>` and inspect the resulting PNGs with an available image-viewing tool. Fix overlap, clipping, overflow, contrast, and incorrect arrows; re-shoot after fixes. For a large page or when requested, use an independent screenshot review if delegation is available and authorized. If screenshots are unavailable, disclose that limitation rather than claiming visual review.
6. Without a shell, deliver the single HTML file directly.
7. Report the bare `http://localhost:<port>/` URL followed by a two-line summary of the page.

The helper requires Python 3.10+ on Linux, WSL, or macOS. Screenshot capture additionally requires `playwright-cli` and its browser. Optional `meta.json` supports a relative HTML `entry` and a `build` label for generated pages; the helper never executes build commands. Static checks catch common offline problems but do not prove that arbitrary JavaScript makes no network requests.
