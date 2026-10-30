---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

# Web Interface Guidelines

Review the requested UI files using [the pinned guidelines](references/command.md).
Read that local reference before reviewing; it contains the rules and output format.
Use the supplied file/pattern or infer the affected files from the current task.
Report actionable findings with file and line evidence. Do not change the product's
framework, permissions, acceptance criteria or existing design intent to satisfy a rule.

ProtoHub vendors this reference from an immutable upstream commit. Do not fetch main
or silently update the rules during a review. Source, hashes, license evidence and this
adaptation are recorded in `harness/skills.lock.json` at the repository root.
The original upstream skill is preserved in `third_party/agent-skills/` for comparison.
