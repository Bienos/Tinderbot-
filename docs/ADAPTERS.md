# Additional authorized adapters

Implement `agent.adapters.Adapter` (`agent.provider_contract` re-exports it):

```python
class Adapter(Protocol):
    async def snapshot(self, thread: dict) -> list[dict]: ...
    async def send(self, thread: dict, text: str, action_id: str, anchor: str) -> str: ...
    async def reconcile(self, thread: dict, action_id: str) -> str | None: ...
```

Messages require `id`, `thread_id`, `sender` (`you`/`them`), `body` and UTC ISO `created_at`. Namespace IDs by provider/account/thread/message, not display name. Preserve chronological source ordering; source IDs must remain stable across retries. Never infer unmatch/deletion from an incomplete listing. Only a positive provider signal establishes deletion or revoked access.

Add an explicit dispatch entry after verifying the platform's permitted operations. Record granted account capabilities separately from technical adapter capabilities, and retain participant consent/disclosure requirements. Add webhook ingestion with authenticated update dedup where supported; otherwise document complete/partial pagination and session expiration behavior. Do not add an arbitrary-origin browser connector.

Before sending, refresh source identity/history, validate the latest anchor, permissions, account rights and conversation revision. Enforce atomic compare-and-send/idempotency at the source when supported. Return a verified provider/DOM message ID, never simply a click result. Persist the action before dispatch; ambiguous failures must not be blindly retried. `reconcile` must observe a previous receipt without creating another send; return None when unavailable.

Test empty threads, changed/edited/deleted content, incomplete lists, stale drafts, revocation, unsupported media, duplicate content, ordering, rate limits, session expiry and a lost receipt after external commit. The current Telegram implementation explicitly lacks arbitrary history fetch and external idempotency; preserve that distinction in any new adapter. The owner-enabled unofficial Tinder implementation now follows this boundary; see TINDER.md for its limitations and automatic sending behavior.
