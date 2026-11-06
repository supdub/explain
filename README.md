# Explain

A Codex skill for self-contained visual HTML explainers, diagrams, simulations, and slide decks. Each explainer runs on its own remembered localhost port and can open offline.

## Install

Clone this repository into your Codex skills directory:

```sh
git clone https://github.com/supdub/explain.git "${CODEX_HOME:-$HOME/.codex}/skills/explain"
```

If an `explain` skill already exists, update that installation rather than overwriting it.

## Use

Ask Codex: `Use $explain to show me how a topic works visually.`

Plain explanation requests without a visual request stay in chat. Existing explainers can be listed, updated, and served again.

## Helper commands

Requires Python 3.10+ on Linux, WSL, or macOS.

```sh
python3 scripts/explain.py list
python3 scripts/explain.py serve my-topic
python3 scripts/explain.py check my-topic
python3 scripts/explain.py shoot my-topic
python3 scripts/explain.py stop my-topic
```

Pages live in `~/.explain/<slug>/index.html`; set `EXPLAIN_DIR` to use another directory. Servers bind to `127.0.0.1` on ports 8800–8999. Ports are remembered across stops and restarts, unless occupied by another service. Local health checks bypass HTTP proxies.

The `shoot` command requires `playwright-cli` and its browser. It captures desktop and mobile screenshots and reports layout probes and browser console output for review. Static checks identify common remote assets and metadata issues; they do not guarantee arbitrary JavaScript never accesses the network.

Optional `meta.json` supports a relative HTML `entry` and a descriptive `build` label. Build commands are never executed.
