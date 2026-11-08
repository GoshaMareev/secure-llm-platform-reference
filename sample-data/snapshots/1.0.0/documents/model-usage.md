# Approved model usage

Only models registered behind the approved gateway may process organization data. Applications must not accept a provider URL, model token, or credential from an end-user request.

Data classification determines which model route is allowed. Restricted content stays on the local inference route. Public synthetic test data may use the deterministic demo gateway.

When retrieved evidence is insufficient, the assistant must refuse instead of asking the model to fill gaps from prior knowledge. Citations must identify the source document selected by retrieval.

