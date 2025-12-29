import os
import subprocess
from typing import Optional, Tuple, List
from agentic_consult.backup.git_utils import GitUtils
from agentic_consult.gemini import GeminiAPIClient

class BackupMetadataManager:
    """
    Manages backup metadata (description, keywords) stored in git config.
    
    NOTE: This metadata is stored in the local .git/config and is NOT included 
    in the git bundle itself. A thought to remember: since this syncs to 
    Drive metadata, a future restore process could potentially retrieve and 
    reconstruct this configuration.
    """
    CONFIG_KEY_DESC = "bundle-backup.description"
    CONFIG_KEY_KEYWORDS = "bundle-backup.keywords"

    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        if not GitUtils.is_git_repo(self.repo_path):
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def get_metadata(self) -> Tuple[Optional[str], Optional[str]]:
        """Returns (description, keywords)."""
        desc = GitUtils.get_config(self.repo_path, self.CONFIG_KEY_DESC)
        keywords = GitUtils.get_config(self.repo_path, self.CONFIG_KEY_KEYWORDS)
        return desc, keywords

    def set_metadata(self, description: Optional[str] = None, keywords: Optional[str] = None):
        """Sets the metadata values."""
        if description:
            GitUtils.set_config(self.repo_path, self.CONFIG_KEY_DESC, description)
        if keywords:
            GitUtils.set_config(self.repo_path, self.CONFIG_KEY_KEYWORDS, keywords)

    def clear_metadata(self):
        """Clears the metadata values."""
        GitUtils.unset_config(self.repo_path, self.CONFIG_KEY_DESC)
        GitUtils.unset_config(self.repo_path, self.CONFIG_KEY_KEYWORDS)

    def generate_proposal(self) -> Tuple[str, str]:
        """
        Analyzes the repository context and uses Gemini to propose metadata.
        Returns (description, keywords).
        Raises ValueError on failure.
        """
        context = self._gather_context()
        if not context:
            raise ValueError("Could not find any repository context (no commits or README).")

        prompt = (
            "Analyze the following repository context and propose metadata for a backup archive. "
            "The metadata will be used for search indexing in Google Drive.\n\n"
            f"{chr(10).join(context)}\n\n"
            "Provide your response in EXACTLY this format:\n"
            "Description: [A one-sentence summary of the repository's purpose and recent changes]\n"
            "Keywords: [A space-separated list of 5-10 keywords, including ticket IDs, error codes, technologies, and tags]\n"
        )

        client = GeminiAPIClient()
        result = client.generate_content(prompt)
        proposal = result["text"]

        new_desc = ""
        new_keywords = ""
        for line in proposal.splitlines():
            if line.lower().startswith("description:"):
                new_desc = line[12:].strip()
            elif line.lower().startswith("keywords:"):
                new_keywords = line[9:].strip()

        if not new_desc or not new_keywords:
             raise ValueError(f"Gemini returned an invalid format: {proposal}")

        return new_desc, new_keywords

    def _gather_context(self) -> List[str]:
        context = []
        # 1. Recent commit messages
        try:
            log = subprocess.run(
                ["git", "log", "-n", "20", "--pretty=format:%s"], 
                cwd=self.repo_path, capture_output=True, text=True, check=True
            ).stdout
            if log:
                context.append("Recent commit messages:\n" + log)
        except Exception:
            pass
            
        # 2. README
        readme_path = None
        for f in os.listdir(self.repo_path):
            if f.lower().startswith("readme"):
                readme_path = os.path.join(self.repo_path, f)
                break
                
        if readme_path and os.path.isfile(readme_path):
            try:
                with open(readme_path, 'r') as f:
                    # Read first 2KB of README
                    context.append("README content snippet:\n" + f.read(2048))
            except Exception:
                pass
        return context
