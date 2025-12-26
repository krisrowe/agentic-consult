"""
Factory for retrieving the configured TaskProvider.
"""
import importlib
from typing import Optional

from agentic_consult.config import load_main_config
from agentic_consult.tasks.providers import TaskProvider

TASK_PROVIDERS = {
    "ticktick": "agentic_consult.tasks.providers.ticktick",
    # Add other providers here
}

def get_task_provider() -> Optional[TaskProvider]:
    config = load_main_config()
    if not config:
        return None

    tasks_config = config.get("tasks", {})
    provider_name = tasks_config.get("provider")
    if not provider_name:
        return None

    provider_module_path = TASK_PROVIDERS.get(provider_name)
    if not provider_module_path:
        return None

    try:
        module = importlib.import_module(provider_module_path)
        # Assuming the provider class is named <ProviderName>Provider
        provider_class_name = f"{provider_name.capitalize()}Provider"
        provider_class = getattr(module, provider_class_name)
        return provider_class()
    except (ImportError, AttributeError):
        return None
