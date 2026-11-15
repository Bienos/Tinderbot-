"""Final deterministic dispatch checks. No model can reserve or authorize an action."""
from agent import storage as s,runtime as rt

class DispatchDenied(Exception):pass

def guard(thread_id,action_id,text,anchor,history):
    actions=s.rows('SELECT a.*,d.body,d.status AS draft_status,d.generator,c.history_hash,c.settings_hash '
                   'FROM actions a JOIN drafts d ON d.id=a.draft_id JOIN draft_context c ON c.draft_id=d.id '
                   'WHERE a.id=? AND a.thread_id=?',(action_id,thread_id))
    threads=s.rows('SELECT * FROM threads WHERE id=?',(thread_id,))
    if not actions or not threads:raise DispatchDenied('Action not reserved for this conversation')
    a=actions[0];t=threads[0]
    if a['status']!='sending' or a['draft_status']!='sending' or a['body']!=text or a['anchor']!=anchor:
        raise DispatchDenied('Action or draft no longer dispatchable')
    if not rt.eligible(t) or a['settings_hash']!=rt.settings_hash():raise DispatchDenied('Paused, revoked or changed profile')
    if not history or history[-1]['id']!=anchor or a['history_hash']!=rt.history_hash(history):raise DispatchDenied('Source content changed')
    if t['platform']!='simulator':
        grants=s.rows('SELECT * FROM grants WHERE thread_id=?',(thread_id,))
        con=s.rows('SELECT * FROM connections WHERE id=?',(t['connection_id'],))
        # The owner's click makes the owner the sender; only automatic sends need the participant's consent.
        if a['automatic'] and not rt.auto_consent(t):
            raise DispatchDenied('Consent or disclosure revoked')
        if not con or not con[0]['enabled'] or not con[0]['can_reply']:
            raise DispatchDenied('Connection revoked')
        if not a['generator'].startswith('LLM-reviewed:'):raise DispatchDenied('No reviewed live reply')
    if a['automatic'] and not rt.auto_allowed(t):raise DispatchDenied('Automatic sending disabled')
    return a
