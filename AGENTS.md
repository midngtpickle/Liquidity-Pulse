# AGENTS.md

**Working instructions for coding agents live in [CLAUDE.md](CLAUDE.md).** That file
carries the setup and run commands, the file map and data contracts, the reasoning rules
for interpreting telemetry, and the code conventions this project expects. Start there.

What the system runs at runtime — which processes exist, what starts them, and what they
write — is described in [docs/AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md). Despite
the file name, there are no LLM agents at runtime: every component is deterministic Python.
