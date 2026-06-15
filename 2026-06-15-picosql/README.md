# PicoSQL

A relational database engine written from scratch in pure Python 3 (stdlib only):
SQL text → tokenizer → parser → planner → executor over a **durable, paged B+tree**
on disk.

> Status: **Phase 1 (plan) complete.** See [PLAN.md](PLAN.md) for the full design,
> feature list, and verification strategy. Implementation in progress.
