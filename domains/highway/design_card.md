# Highway design card

Coordinator: `Coordinator.handle` owns one Enterprise state for the whole feed.

Specialist 1, EventAnalyst, classifies the text and does not call tools.
Specialist 2, PolicyPlanner, is the handbook rules in `plan_event`. It chooses the calls.
Specialist 3, ExecutionVerifier, rejects any call with `ok: false`.

The classifier is a deterministic parser, not a hosted model. Gemini and Ollama are not on this path, because a match-style offline run must not need the network and a model is not allowed to authorize a write.

Guardrail: a tool error is logged and not retried. Noise writes nothing. An unconfirmed report escalates.

Scenario date is 2027-03-08 from the handbook.
