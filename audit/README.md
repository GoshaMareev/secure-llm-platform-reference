# Prompt-audit plane

The reference writes audit events to a volume that is not mounted by Fluent Bit. The default event stores a prompt digest and length rather than raw content.

`event.schema.json` documents the portable event contract. A production adapter should authenticate to the destination, encrypt transport, buffer to an access-controlled disk path, expose delivery metrics, and define retention and replay behavior.

The repository intentionally does not include a real SIEM endpoint, certificate, tenant ID, detection rule, or customer field mapping.

