"""Generate the per-customer secrets for a new isolated instance (option 4: one server per customer).

Usage: python scripts/new_customer.py <customer-slug>
Prints the environment variables to set on that customer's own Render service. Nothing is stored here.
Each customer gets a unique TOKEN_ENCRYPTION_KEY (their Tinder token is encrypted with it) and a unique
DASHBOARD_TOKEN (their login). Never reuse either between customers; never put a Tinder token in env.
"""
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.vault import generate_key  # noqa: E402

if len(sys.argv) != 2 or not re.fullmatch(r'[a-z0-9][a-z0-9-]{2,30}', sys.argv[1]):
    sys.exit('usage: new_customer.py <customer-slug: lowercase letters, digits, dashes>')
slug = sys.argv[1]
env = {
    'TOKEN_ENCRYPTION_KEY': generate_key(),
    'DASHBOARD_TOKEN': secrets.token_urlsafe(32),
    'TINDER_ENABLED': 'true',
    'SEED_SIMULATOR': 'false',
    'LLM_PROVIDER': 'anthropic',
    'ANTHROPIC_MODEL': 'claude-sonnet-5-5',
    'TINDER_REQUESTS_PER_MINUTE': '30',
    'TINDER_REQUESTS_PER_HOUR': '300',
    'PUBLIC_ORIGIN': f'https://tinderbot-{slug}.onrender.com',
}
print(f'# Environment for customer "{slug}" (set on their own Render service; keep this output private)')
for k, v in env.items():
    print(f'{k}={v}')
print('# Also set ANTHROPIC_API_KEY (your key) directly in Render. Do NOT set TINDER_AUTH_TOKEN:')
print('# the customer pastes their token in their own dashboard, where it is verified and encrypted.')
