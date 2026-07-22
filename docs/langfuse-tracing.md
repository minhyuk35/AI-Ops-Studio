# Langfuse tracing

## Trace contract

One customer message is one trace. Multi-turn messages share a `session_id`.

```text
answer-customer-inquiry (span)
├── retrieve-support-prompt (retriever)
└── generate-support-reply (generation)
```

Stable observation names are intentional because dashboards and evaluators may depend on them.

## Captured fields

- Root input/output: customer question and final answer
- Context: `user_id`, `session_id`, environment, feature/channel tags
- Metadata: request ID, organization ID, order ID
- Generation: Gemini model, linked Langfuse prompt version, interaction ID
- Usage: exclusive input, cached input, output, reasoning, tool-use and total tokens
- Privacy: emails, Korean mobile numbers and card-like numbers are masked before export

## Live verification

After filling `.env`, create one real trace:

```powershell
cd "D:\AI Ops Studio"
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH="services/core-api"
python scripts/verify_langfuse_trace.py
```

Then open the Japan project in Langfuse and inspect the trace named
`answer-customer-inquiry`. Confirm the observation hierarchy, token usage,
prompt version link, session, environment and masking.

