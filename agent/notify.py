"""Transactional outbox. Retry known pre-delivery failures; ambiguous SMTP delivery is quarantined."""
import os,smtplib,time,ssl
from email.message import EmailMessage
from agent import storage as s,runtime as rt

def maybe_email(kind,thread_name,body,notification_id=0):
    if not rt.settings()['email'] or not os.getenv('SMTP_HOST') or not os.getenv('NOTIFY_TO'):return False
    msg=EmailMessage()
    msg['Subject']='Conversation agent: activity requires review'
    msg['Message-ID']=f'<agent-notification-{notification_id}@local.invalid>'
    msg['From']=os.environ['NOTIFY_FROM'];msg['To']=os.environ['NOTIFY_TO']
    # No names, contacts, time, location or chat bodies in email.
    msg.set_content('A conversation outcome changed. Open your authenticated dashboard to review it.')
    with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=15) as server:
        server.starttls(context=ssl.create_default_context())
        if os.getenv('SMTP_USERNAME'):server.login(os.environ['SMTP_USERNAME'],os.environ['SMTP_PASSWORD'])
        server.send_message(msg)
    return True

def deliver_outbox():
    for row in s.rows("SELECT o.*,n.kind,n.body FROM outbox o JOIN notifications n ON n.id=o.notification_id WHERE o.status='queued' AND o.available<=?",(time.time(),)):
        if not rt.settings()['email'] or not os.getenv('SMTP_HOST'):continue # In-app delivery already committed.
        with s.connect() as db:
            c=db.execute("UPDATE outbox SET status='sending',attempts=attempts+1 WHERE id=? AND status='queued'",(row['id'],))
            if not c.rowcount:continue
        try:
            delivered=maybe_email(row['kind'],'',row['body'],row['notification_id'])
            status='sent' if delivered else 'queued';error=None
        except (smtplib.SMTPConnectError,smtplib.SMTPAuthenticationError,ConnectionRefusedError):
            status='queued' if row['attempts']<4 else 'failed';error='SMTP setup failed'
        except Exception:
            status='uncertain';error='SMTP result uncertain; no automatic retry'
        with s.connect() as db:
            db.execute('UPDATE outbox SET status=?,error=?,available=? WHERE id=?',(status,error,time.time()+min(300,2**min(row['attempts']+1,8)),row['id']))
        rt.metric('notification_'+status)
