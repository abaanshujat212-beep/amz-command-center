# Grounded AI source and context contract

Every AXATY AI answer is constrained to one server-authorized tenant context. The context may additionally name marketplace and advertising profile, but those fields never widen tenant access.

## Required evidence for metric claims

Each numeric claim must include:

- a stable source identifier;
- provider and source scope;
- observation timestamp and data-through date;
- freshness state and completeness ratio;
- an internal, tenant-scoped **Show data** route.

Stale, partial, missing or blocked evidence must be disclosed. If required evidence is unavailable, the answer refuses the claim rather than estimating or presenting an empty result as success.

## Tool boundary

Only the existing read-only Copilot SQL path and generated system map are allowed. The grounded-response layer has no Amazon mutation tool and no database write tool. Recommendations remain text; deterministic capability, approval and worker paths remain authoritative.

Workspace documents, source labels and query results are evidence data, not trusted instructions. Unknown domains, sources or tools fail closed.

## Contract implementation

`services/copilot/grounding.py` defines the context envelope, source reference, metric claim, response and validator. Callers must validate before rendering a metric answer. Tests cover source completeness, freshness disclosure, tenant context, tool allowlisting and refusal behavior.

This contract does not claim that an external model or provider is production-ready; model serving and usage controls remain separate work.
