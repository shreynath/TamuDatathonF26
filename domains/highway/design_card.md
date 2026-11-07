# Highway design card

Coordinator: `plan_event` takes one event, parses incidents, then runs one shared Enterprise state.

Specialists are responsibilities inside that function, not separate processes: supply and production move orders, dealer and customer notify and assign loaners, quality holds lots and splits sold from unsold.

The rule parser is the default. An Ollama key can be added later. The model does not call write tools.

Guardrail: a tool error is logged and not retried. Noise writes nothing. An unconfirmed report escalates.

Scenario date is 2027-03-08 from the handbook.
