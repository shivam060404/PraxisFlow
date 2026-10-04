# Security boundaries

PraxisFlow treats the verified token as proof of identity, not proof of
current access. Authenticated requests resolve the user by both `id` and
`tenantId`, and only users with `ACTIVE` status may continue. Suspending or
deleting a user therefore takes effect immediately rather than waiting for
JWT expiry.

Resource authorization checks tenant ownership before resource ownership.
Matching a user ID in another tenant can never bypass tenant isolation.

ABAC and OPA integrations fail closed while they are unconfigured. They must
not return an allow decision as a placeholder.

LangGraph HITL state uses the PostgreSQL checkpointer by default. Production
and staging startup fail when the durable checkpointer cannot initialize;
in-memory state is available only for explicit non-production development or
test environments.
