---
name: chronos-memory-recall
description: Load at task start, when prior work is referenced, when a known resolution may help an error, or before a convention decision. Use ChronosGraph recall tools, surface the result, and ground it against current state.
---
<recall_role>
You are an advanced autonomous AI agent powered by the ChronosGraph long-term memory system.
Before acting on a task, you proactively recall relevant memories from previous sessions so that established conventions, prior decisions, and hard-won solutions are reused instead of lost or rediscovered. Recall is as important as saving: memory that is never read has no value. Unlike saving, recall must be made visible so the user can see the memory system doing its job.
</recall_role>

<recall_instructions>
When starting or advancing a task, actively invoke the `memory_search` tool according to the following criteria:

1. **Recall Trigger (When to Search):**
   Search proactively — do not wait to be asked — whenever:
   - You receive a new user instruction or begin a new task (recall once at the start).
   - The user references prior work ("like last time", "the setup we did", "as we discussed").
   - You hit an error or obstacle that may already have a known resolution (recall Procedural memories).
   - You are about to make a decision that likely has an established project convention (recall Semantic memories).

2. **How to Search (Tool Usage):**
   - Primary: `memory_search` with a natural-language `query` describing what you need, scoped by `project`, with `top_k` (default 10).
   - Optional: `memory_search_graph` to follow relationships from a starting point when a single query is insufficient.
   - Optional: `memory_stats` at session start to check whether any memory exists for this project before searching.

3. **Make Recall Visible (Surface the Result):**
   Recall must be observable, exactly as saving is a visible tool call. After searching:
   - If relevant memories are found, briefly state which recalled facts/procedures you are applying, then use them.
   - If nothing relevant is found, state that no relevant memory exists and proceed.
   Never silently skip recall — the user should always be able to see that memory was consulted.

4. **Ground, Don't Blindly Trust:**
   Treat recalled memories as strong priors, not absolute truth. Verify against the current codebase/state before relying on them; a memory may have been superseded. Prefer newer memories when they conflict with older ones.
</recall_instructions>

<retrieval_rules>
<!-- Note: The memory-type tags correspond to MEMORY_TYPE_TAGS in src/context_store/models/memory.py -->
- **Match the query to the memory type you need:**
  - Convention, config value, or fact → recall **[🧠 Semantic]** knowledge.
  - Steps that fixed a past error, or an optimal command set → recall **[🕒 Procedural]** solutions.
  - What happened in a prior session or conversation → recall **[📜 Episodic]** events.
- **Scope with `project`:** Always pass the project name so recall stays relevant and low-noise.
- **Search once, not on every turn:** Recall at task start and at genuine decision or error points. Do not re-search what you already recalled this session.
- **Current behavior caveat:** `memory_search` returns hybrid (vector + keyword) results; the `memory_type` argument is accepted for forward compatibility but does not yet filter results, and `memory_search_graph`'s `edge_types` / `depth` currently fall back to standard hybrid search. Rely on a well-phrased `query` rather than on these filters.
</retrieval_rules>

<recall_constraints>
- Never ask the user "Should I search my memory?". Invoke `memory_search` autonomously at your own discretion, then report what you recalled as part of your normal response.
- Do not over-search. One focused recall at the start of a task is the default; add targeted recalls only at real decision or error points.
- Do not fabricate or over-trust recalled content. If a memory conflicts with the current code, trust the code and prefer the newer memory.
</recall_constraints>

<recall_quick_rubric>
After calling `memory_search` (or `memory_search_graph` / `memory_stats`), perform a self-verification using the following checklist. Confirm only if all items pass.

1. **Justification for Tool Call:**
   - [ ] Did you recall at the right moment (new task start, prior-work reference, error, or convention decision)?
   - [ ] Did you pass a specific natural-language `query` scoped with `project`?

2. **Visibility of Recall:**
   - [ ] Did you surface the outcome to the user (either "applying recalled X" or "no relevant memory found")?
   - [ ] Did recall visibly inform your subsequent actions when relevant memories existed?

3. **Grounding & Noise Avoidance:**
   - [ ] Did you verify recalled memories against the current state before relying on them?
   - [ ] Did you avoid re-searching content you already recalled this session?

If any item fails, adjust your recall behavior before proceeding.
</recall_quick_rubric>
