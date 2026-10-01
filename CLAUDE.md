# Project entry point

Read [HANDOFF.md](HANDOFF.md) before taking task action. It routes you to the active project context and the repository's authoritative principles, permissions, and role guidance.

Do not duplicate those rules in this file. Follow the documents named by `HANDOFF.md`.

## Role agents and parallel operation

`.claude/agents/*.md` is the shared role contract and Claude Code runtime definition
for both Claude Code and Codex. Read
`meta/agent-runtime-mapping.md` before dispatching to confirm the role-to-runtime
mapping. Do not create a runtime-specific copy of the shared role contract.

Claude and Codex may develop this repository in parallel. Before starting a slice, read
the active context and inspect relevant open PRs. Do not edit another runtime's
unmerged project or shared `meta/**` changes without first coordinating through the
project branch and PR review.

When work comes from a Linear ticket or runs under Orca, follow `meta/orchestration.md`
(ADR-0068). The default runtime per role for mixed Claude/Codex operation is in
`meta/agent-runtime-mapping.md`.
