# OpenDate-derived Tinder integration

`agent/tinder.py` adapts the async Tinder connector design, profile resolution,
private endpoint mapping and token-based pagination from:

- Project: OpenDate by Sumit Aich
- Repository: https://github.com/sumitaich1998/OpenDate
- Inspected revision: ba179f23b14a416ef9514e579cab6f7431e3ec1c
- Original: src/opendate/connectors/tinder.py
- License: MIT; complete notice in licenses/OpenDate-MIT.txt

Local changes: messaging-only scope, no swiping or app-mimicking headers;
read-only retries; no POST retry; strict source/sender/identity validation;
complete-history reconciliation; durable receipt candidates with read-back;
no synthesized successful sends; local permissions, automatic mode and revocation;
secret-free errors and dashboard connection controls. This is unofficial access,
not a Tinder partnership or a claim of written platform permission.
