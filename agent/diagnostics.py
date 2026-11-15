"""Error metadata only: never exception text, request bodies, credentials or frame locals."""
import json
import traceback
from uuid import uuid4


def report_failure(exc, operation):
    from agent import runtime as rt
    reference = uuid4().hex[:16]
    frames = traceback.extract_tb(exc.__traceback__)[-6:]
    metadata = {
        'event': 'request_error', 'reference': reference, 'operation': operation,
        'exception_type': type(exc).__name__,
        'frames': [{'file': f.filename.rsplit('/', 1)[-1], 'function': f.name, 'line': f.lineno} for f in frames],
    }
    print(json.dumps(metadata), flush=True)
    try:
        rt.audit(None, 'request_error', 'Unexpected error during ' + operation + '; reference ' + reference)
        rt.metric('request_failures')
    except Exception:
        # Logging must still work when the storage layer itself has failed.
        pass
    return reference


async def tinder_startup_check():
    """Opt-in read-only profile check for diagnosing a failed owner connection.

    Does not create/enable a connection, import conversations or call a sending
    endpoint. Existing account cooldowns and request budgets still apply.
    """
    from agent import tinder, runtime as rt
    if not tinder.configured():
        print(json.dumps({'event': 'tinder_preflight', 'state': 'not_configured'}), flush=True)
        return
    if rt.settings()['paused']:
        print(json.dumps({'event': 'tinder_preflight', 'state': 'paused'}), flush=True)
        return
    try:
        async with tinder.client() as api:
            await api.profile()
    except tinder.TinderError as exc:
        allowed = {'tinder_token_missing_or_invalid', 'connection_paused', 'rate_limited',
                   'account_restriction_requires_review', 'session_expired_or_access_denied',
                   'source_not_observed', 'source_server_error', 'read_transport_failed',
                   'invalid_profile', 'invalid_source_identity', 'invalid_source_json', 'invalid_source_encoding',
                   'unexpected_source_shape', 'source_response_too_large', 'request_rejected',
                   'verification_requires_manual_review', 'redirect_requires_review'}
        code = str(exc) if str(exc) in allowed else 'tinder_request_failed'
        print(json.dumps({'event': 'tinder_preflight', 'state': 'rejected', 'code': code}), flush=True)
    except Exception as exc:
        reference = report_failure(exc, 'tinder_preflight')
        print(json.dumps({'event': 'tinder_preflight', 'state': 'error', 'reference': reference}), flush=True)
    else:
        print(json.dumps({'event': 'tinder_preflight', 'state': 'ok'}), flush=True)
