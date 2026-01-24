"""Gmail API SDK using google-auth credentials."""

from agentic_consult.sdk.gmail.labels import add_label, remove_label, archive, list_inbox

__all__ = ['add_label', 'remove_label', 'archive', 'list_inbox']
