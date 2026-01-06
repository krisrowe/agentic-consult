import os
import subprocess
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime

class GitUtils:
    @staticmethod
    def is_git_repo(path: str) -> bool:
        return os.path.isdir(os.path.join(path, ".git"))

    @staticmethod
    def get_last_fetch_time(repo_path: str) -> Optional[str]:
        """Returns ISO 8601 timestamp of last fetch, or None."""
        try:
            fetch_head = os.path.join(repo_path, ".git", "FETCH_HEAD")
            if os.path.exists(fetch_head):
                mtime = os.path.getmtime(fetch_head)
                return datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            pass
        return None

    @staticmethod
    def has_remotes(repo_path: str) -> bool:
        try:
            result = subprocess.run(["git", "remote"], cwd=repo_path, capture_output=True, text=True, check=True)
            return bool(result.stdout.strip())
        except Exception: return False

    @staticmethod
    def get_remote_url(repo_path: str, remote: str = "origin") -> Optional[str]:
        try:
            result = subprocess.run(["git", "remote", "get-url", remote], cwd=repo_path, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except Exception: return None

    @staticmethod
    def get_author_stats(repo_path: str, limit: int = 100) -> Dict[str, int]:
        """Returns a dict of email -> count of commits."""
        stats = {}
        try:
            # Get just emails from log
            cmd = ["git", "log", "--format=%ae"]
            if limit:
                cmd.extend(["-n", str(limit)])
            
            result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, check=True)
            for email in result.stdout.splitlines():
                email = email.strip()
                if email:
                    stats[email] = stats.get(email, 0) + 1
        except Exception: pass
        return stats

    @staticmethod
    def get_commit_history_stats(repo_path: str, last_n: int = 10) -> Dict[str, Any]:
        """
        Retrieves detailed commit history statistics for identity resolution.
        Returns:
            {
                "first_commit_author": str,
                "last_n_authors": List[str],
                "total_commit_count": int,
                "author_counts": Dict[str, int]
            }
        """
        stats = {
            "first_commit_author": None,
            "last_n_authors": [],
            "total_commit_count": 0,
            "author_counts": {}
        }
        try:
            # 1. Get first commit author
            # git log --reverse --format=%ae | head -n 1
            res_first = subprocess.run(
                ["git", "log", "--reverse", "--format=%ae"], 
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            first_line = res_first.stdout.splitlines()
            if first_line:
                stats["first_commit_author"] = first_line[0].strip()

            # 2. Get last N authors (most recent first)
            # git log -n 10 --format=%ae
            res_last_n = subprocess.run(
                ["git", "log", "-n", str(last_n), "--format=%ae"],
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            stats["last_n_authors"] = [line.strip() for line in res_last_n.stdout.splitlines() if line.strip()]

            # 3. Get all authors for total counts
            # git log --format=%ae
            res_all = subprocess.run(
                ["git", "log", "--format=%ae"],
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            all_lines = res_all.stdout.splitlines()
            stats["total_commit_count"] = len(all_lines)
            
            for line in all_lines:
                email = line.strip()
                if email:
                    stats["author_counts"][email] = stats["author_counts"].get(email, 0) + 1
                    
        except Exception:
            pass
        return stats

    @staticmethod
    def is_dirty(repo_path: str) -> bool:
        try:
            # --porcelain=v2 lists headers (#), changed entries (1, 2, u), untracked (?), ignored (!)
            # We care about 1, 2, u, ?. Ignored (!) does not make it dirty.
            result = subprocess.run(["git", "status", "--porcelain=v2"], cwd=repo_path, capture_output=True, text=True, check=True)
            for line in result.stdout.splitlines():
                if line.startswith(('1', '2', 'u', '?')):
                    return True
            return False
        except Exception: return False

    @staticmethod
    def get_status_stats(repo_path: str) -> Dict[str, int]:
        stats = {'staged': 0, 'unstaged': 0, 'untracked': 0, 'ignored': 0}
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain=v2", "--ignored"], 
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            for line in result.stdout.splitlines():
                if not line: continue
                code = line[0]
                
                if code == '?':
                    stats['untracked'] += 1
                elif code == '!':
                    stats['ignored'] += 1
                elif code in ['1', '2', 'u']:
                    # Format: 1 XY sub mH mI mW hH hI path
                    # Field 1 (index 1 in split) is XY.
                    parts = line.split(' ')
                    if len(parts) > 1:
                        xy = parts[1]
                        x, y = xy[0], xy[1]
                        
                        # X checks (Index/Staged)
                        if x not in ['.', '!', '?']: # '.' is unmodified for that side
                            stats['staged'] += 1
                            
                        # Y checks (Worktree/Unstaged)
                        if y not in ['.', '!', '?']:
                            stats['unstaged'] += 1
        except Exception: pass
        return stats

    @staticmethod
    def get_repo_state_hash(repo_path: str) -> str:
        try:
            result = subprocess.run(["git", "show-ref"], cwd=repo_path, capture_output=True, text=True)
            return hashlib.md5(result.stdout.encode()).hexdigest()
        except Exception: return ""

    @staticmethod
    def get_config(repo_path: str, key: str) -> Optional[str]:
        try:
            result = subprocess.run(["git", "config", "--local", "--get", key], cwd=repo_path, capture_output=True, text=True)
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception: pass
        return None

    @staticmethod
    def set_config(repo_path: str, key: str, value: str):
        try:
            subprocess.run(["git", "config", "--local", key, value], cwd=repo_path, check=True)
        except Exception: pass

    @staticmethod
    def unset_config(repo_path: str, key: str):
        try:
            subprocess.run(["git", "config", "--local", "--unset-all", key], cwd=repo_path)
        except Exception: pass

    @staticmethod
    def get_remote_status(repo_path: str) -> Dict[str, Any]:
        """Returns dict with status ('ahead', 'behind', 'diverged', 'clean', 'unknown') and counts."""
        result_data = {'status': 'unknown', 'unpushed': 0, 'unpulled': 0}
        try:
            result = subprocess.run(
                ["git", "status", "--branch", "--porcelain=v2"], 
                cwd=repo_path, capture_output=True, text=True, check=True
            )
            
            unpushed = 0
            unpulled = 0
            has_upstream = False
            
            for line in result.stdout.splitlines():
                if line.startswith("# branch.ab"):
                    # Format: # branch.ab +A -B
                    parts = line.split(' ')
                    if len(parts) >= 4:
                        # +A (unpushed)
                        ahead_str = parts[2]
                        if ahead_str.startswith('+'):
                            unpushed = int(ahead_str[1:])
                        # -B (unpulled)
                        behind_str = parts[3]
                        if behind_str.startswith('-'):
                            unpulled = int(behind_str[1:])
                    has_upstream = True

            if not has_upstream:
                return result_data 

            result_data['unpushed'] = unpushed
            result_data['unpulled'] = unpulled

            if unpushed > 0 and unpulled > 0:
                result_data['status'] = 'diverged'
            elif unpushed > 0:
                result_data['status'] = 'ahead'
            elif unpulled > 0:
                result_data['status'] = 'behind'
            else:
                result_data['status'] = 'clean'
            
            return result_data
        except Exception: return result_data
