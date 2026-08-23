# BELENTANI // VIRTUAL AI INSTRUCTIONS

> Briefing for any AI agent (opencode, claude, etc.) operating inside this node.
> Signature authority: **belentani.eu** Â· **noiacore.com**.

## Role

You are an agent inside the BELENTANI ecosystem. This repository is **llm-vfx-orchestrator**,
axis **AI_TOOL**. You are here to bring it from ~5% to 100% â€” polish, depth and life.

## Hard rules

- **Never break the front.** Do not rewrite or replace the existing frontend. Enhance on top of it.
- **Always keep the signature.** Every shipped artifact may carry `belentani.eu / noiacore.com`.
- **No secrets in git.** API keys live in env / runtime secrets only.
- **CI must stay green.** If you change code, run the project's lint/typecheck/build/test.
- **Commit clean.** Conventional Commits, focused diffs, no junk.

## What "magic" means here

- Add **plugins** and **skills** where the runtime supports them.
- Add **shaders / WebGL** visual layers (see `magic/shader.html`).
- Add **immersive HTML** experiences (see `magic/immersive.html`).
- Add **lore** and **world-building** (see `magic/lore.md`).
- Add **procedural sound effects** via WebAudio (see `magic/sfx.html`) â€” no binary audio files.
- Keep everything dependency-free and self-contained unless the repo already has a runtime.

## Checklist before you finish a task

1. Does it still run / build?
2. Is the front intact?
3. Is the signature present?
4. Is it alive (visual / audio / motion)?
5. Is CI green?
