# ADR 0003: Separate collection from normalization

Status: accepted

Core connectors normalize authorized exports or API objects but do not own credentials, OAuth consent, or cloud pagination. This keeps the public core testable and prevents credential policy from being embedded in domain logic. Deployment-specific collectors can wrap each normalizer.
