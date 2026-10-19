# Scope and safety boundary

Project SWING is a power-grid **simulation and decision-support** application. Its IEEE 39-bus and 118-bus cases are software models. Neither the supplied code nor this reconstruction is an interface to operating grid equipment, and it must not be described as a certified operational control or compliance system.

The reference application has two independent FastAPI services: a Digital Twin service for physics and grid state, and an AI Agent service that reads and proposes actions through the Twin's HTTP API. Two static browser dashboards consume those services. The Agent must not import the Twin's internal model or mutate its network directly. Both services may use a local event store when co-located.

Changing simulated load, generator dispatch, line status, or stress settings is a simulated state mutation. Online agent recommendations require an explicit, identifiable operator approval before execution. The supplied source allows unauthenticated Twin writes and stores pending Agent proposals only by grid; those are reference defects, not acceptable public deployment behavior. New authentication, proposal binding, expiry, rejection, and rollback safeguards are engineering improvements that must be documented and tested against source behavior.

Until those safeguards pass, run the services on loopback in a private local environment. A public endpoint must fail closed for writes without verified operator identity and approved action context. External SCADA, utility telemetry, or equipment-control connectors are outside this project; adding any such integration requires separate review and authorization.

Forecasts, risk scores, regulatory retrieval, and AI-generated text are decision aids. Preserve the supplied scientific definitions unless a documented defect justifies a change. Do not present historical CSV or training-window predictions as live measurements, or a regulatory summary as legal certification.
