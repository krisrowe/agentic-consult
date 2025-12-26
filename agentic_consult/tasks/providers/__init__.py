"""Abstract Base Class for all task providers."""
from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class TaskProvider(ABC):
    @abstractmethod
    def create_task(self, task: Dict) -> Optional[str]:
        """
        Creates a task in the remote system.
        Returns the remote provider's ID for the task.
        """
        pass

    @abstractmethod
    def update_task(self, provider_id: str, task: Dict) -> bool:
        """
        Updates a task in the remote system.
        Returns True on success.
        """
        pass

    @abstractmethod
    def sync(self, tasks: List[Dict]) -> bool:
        """
        Synchronizes all 'dirty' tasks with the remote system.
        - Creates tasks that have no provider_id.
        - Updates tasks that have a provider_id.
        - Updates the task objects in the list with the new provider_id and state.
        Returns True if all operations succeeded.
        """
        pass
