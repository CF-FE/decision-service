---
name: decision-service
description: Use Decision Service for a finite choice, predicate, or score when authorized, including workflow next actions and role model selection. Prepare bounded inputs, read back decisions, and report application or result through the original executor.
---

# Decision Service

Use the connected Decision Service MCP tools. Inspect the tool schema before calling. When working in the Decision Service repository through an established HTTP client, follow `docs/api-contract.md` and use the caller credential configured by the host. If the connection is missing, direct the user to plugin connection settings and keep credentials out of the conversation.

- `evaluate_decision` accepts the v1 decision request, including `schema_version: 1`, `kind`, `question` and `context`. For a choice, provide the frozen candidates. For a score, provide the ordered levels.
- `get_decision` reads a record using either `decision_id` or `request_id`.
- `record_decision_feedback` accepts the original executor's v1 application, result, or correction event.

- Call when a new decision is needed and its options or rubric are known. Follow an already determined rule directly. Give the service only the question, relevant context and currently legal candidates. For role models, filter the candidate list by real host capability first. Use `recall: skip` when the inputs suffice, or choose only authorized banks. Keep credentials out of payloads and omit model-call prices and cash cost estimates from usage.
- Save the stable `request_id` and full input before requesting a decision that may be applied. On missing response, query by that ID. If it is processing, read back later at the original workflow boundary. On a conflict, compare the frozen input; a changed decision needs a new request ID.
- For executable choices, recheck the original task and snapshot before applying the exact frozen candidate through the existing executor. Only a complete, suggested response with a still valid candidate can be applied. Follow the original fallback for stale inputs, refusals, unavailable or unknown decisions, and requests for review or replanning. A decision is neither authorization nor proof of execution.
- Record application and execution result from the original system, with stable event IDs and actual readback. Keep recommended, launch and effective model configurations separate; unknown effective values remain unknown. Report result coverage from source observations, including known missing results, and preserve unknown scope. Usage can be omitted.
- Keep pending feedback in the original checkpoint. Retry the same event and revision until its receipt is known; send quality updates as later complete revisions. A receipt only confirms storage. Readback and feedback retry do not replay work, create a role, or advance a workflow.
