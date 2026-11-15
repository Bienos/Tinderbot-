"""The executable, platform-independent adapter boundary.

An adapter returns normalized thread-local messages, sends with an action key/anchor,
and attempts reconciliation without resending. Capability/permission checks remain
in the application and adapter; technical access never establishes authorization.
See docs/ADAPTERS.md before adding a supported platform.
"""
from agent.adapters import Adapter, StaleAction, UnsupportedPlatform
__all__=['Adapter','StaleAction','UnsupportedPlatform']
