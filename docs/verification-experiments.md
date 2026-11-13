# Verification experiments and action learning

The Verification page includes an owner/admin experiment workspace. Register a hypothesis, success metric, control or baseline description, entity, and start date. Start and complete the plan explicitly; completion records the end date. Every plan and outcome write is added to the tenant audit log.

Record an operator observation with its success metric, optional value/sample size, and a required evidence note. To link an AXATY action, provide its ID and horizon (T+1, T+3, T+7, T+14 or T+30). The service accepts only a `COMPLETE` snapshot for the same entity, whose verification window is not confounded. The recorded direction must match the snapshot outcome. Confounded outcomes remain visible in verification but do not enter action-learning aggregates.

History is tenant scoped. It shows the number of observations, improved/worsened counts, success rate over improved/worsened/neutral observations, mean recorded metric and sample size. Fewer than five observations are labeled low sample. Operator-entered observations remain descriptive and are not presented as verified causal impact.

API: `GET /api/verification/experiments` lists plans and evidence; `POST` creates a plan or appends an outcome (include `experimentId` to record an outcome); `PATCH` transitions a plan from planned to running/completed/cancelled or running to completed/cancelled. Mutations require an owner or admin session.
