"""
Commit Caster — I2I notification system for fleet repos.

Scans watched repos for I2I-prefixed commits and posts notifications.
Can run as GitHub Action or standalone CLI.
"""
import json
import os
import subprocess
import urllib.request
import urllib.error
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import List, Optional
import re


@dataclass
class I2ICommit:
    """Represents an I2I-tagged commit."""
    sha: str
    repo: str
    message: str
    author: str
    timestamp: str
    message_type: str = ""  # TELL, ASK, BOTTLE, BEACON, etc.
    
    def __post_init__(self):
        # Extract I2I message type from commit prefix
        match = re.match(r'\[I2I:(\w+)', self.message)
        if match:
            self.message_type = match.group(1)


@dataclass
class CastResult:
    """Result of a cast operation."""
    scanned_repos: int
    found_commits: int
    posted_notifications: int
    errors: List[str] = field(default_factory=list)


class CommitCaster:
    """Scans repos and posts I2I notifications."""
    
    def __init__(self, github_token: str = None):
        self.token = github_token or os.environ.get("GITHUB_TOKEN", "")
        self.watched: List[str] = []
        self.seen_shas: set = set()
    
    def watch(self, repo: str):
        """Add a repo to the watch list."""
        self.watched.append(repo)
    
    def _api_get(self, url: str) -> dict:
        """Make an authenticated GitHub API request."""
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"token {self.token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            return {"error": str(e)}
    
    def _api_post(self, url: str, data: dict) -> dict:
        """Make an authenticated GitHub API POST request."""
        body = json.dumps(data).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Authorization", f"token {self.token}")
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
        except Exception as e:
            return {"error": str(e)}
    
    def scan_repo(self, repo: str, prefix: str = "[I2I", limit: int = 10) -> List[I2ICommit]:
        """Scan a repo for recent I2I-tagged commits."""
        url = f"https://api.github.com/repos/{repo}/commits?per_page={limit}"
        data = self._api_get(url)
        
        if "error" in data:
            return []
        
        commits = []
        for c in data:
            msg = c.get("commit", {}).get("message", "")
            sha = c.get("sha", "")
            
            if msg.startswith(prefix) and sha not in self.seen_shas:
                commits.append(I2ICommit(
                    sha=sha,
                    repo=repo,
                    message=msg,
                    author=c.get("commit", {}).get("author", {}).get("name", "unknown"),
                    timestamp=c.get("commit", {}).get("author", {}).get("date", ""),
                ))
                self.seen_shas.add(sha)
        
        return commits
    
    def post_notification(self, target_repo: str, commits: List[I2ICommit]) -> Optional[str]:
        """Post a notification issue for discovered commits."""
        if not commits:
            return None
        
        body = f"**Scanned:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
        for c in commits:
            body += f"### [{c.message_type}] {c.repo}\n"
            body += f"- **SHA:** `{c.sha[:7]}`\n"
            body += f"- **Author:** {c.author}\n"
            body += f"- **Message:** {c.message}\n\n"
        
        result = self._api_post(
            f"https://api.github.com/repos/{target_repo}/issues",
            {
                "title": f"[I2I:BEACON] Fleet Activity — {len(commits)} commits",
                "body": body,
                "labels": ["i2i", "beacon"],
            }
        )
        
        return result.get("html_url") or result.get("error")
    
    def cast(self, target_repo: str = None, prefix: str = "[I2I") -> CastResult:
        """Run a full cast: scan all watched repos, post notifications."""
        result = CastResult(scanned_repos=len(self.watched), found_commits=0, posted_notifications=0)
        
        all_commits = []
        for repo in self.watched:
            commits = self.scan_repo(repo, prefix)
            all_commits.extend(commits)
            if "error" in commits:
                result.errors.append(f"Error scanning {repo}")
        
        result.found_commits = len(all_commits)
        
        if all_commits and target_repo:
            url = self.post_notification(target_repo, all_commits)
            if url and "error" not in str(url):
                result.posted_notifications = 1
            else:
                result.errors.append(f"Post error: {url}")
        
        return result


# ── Tests ──────────────────────────────────────────────

import unittest
from unittest.mock import patch, MagicMock


class TestCommitCaster(unittest.TestCase):
    def test_watch(self):
        cc = CommitCaster("fake-token")
        cc.watch("SuperInstance/oracle1-vessel")
        self.assertEqual(len(cc.watched), 1)
    
    def test_i2i_commit_type(self):
        c = I2ICommit(sha="abc", repo="test", message="[I2I:TELL] hello", author="oracle1", timestamp="")
        self.assertEqual(c.message_type, "TELL")
    
    def test_i2i_commit_no_prefix(self):
        c = I2ICommit(sha="abc", repo="test", message="regular commit", author="oracle1", timestamp="")
        self.assertEqual(c.message_type, "")
    
    def test_scan_filters_prefix(self):
        cc = CommitCaster("fake-token")
        mock_data = [
            {"sha": "aaa", "commit": {"message": "[I2I:TELL] hello", "author": {"name": "o1", "date": "2026-01-01"}}},
            {"sha": "bbb", "commit": {"message": "regular commit", "author": {"name": "o1", "date": "2026-01-01"}}},
        ]
        with patch.object(cc, '_api_get', return_value=mock_data):
            commits = cc.scan_repo("test/repo")
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].message_type, "TELL")
    
    def test_scan_deduplicates(self):
        cc = CommitCaster("fake-token")
        mock_data = [
            {"sha": "aaa", "commit": {"message": "[I2I:TELL] hello", "author": {"name": "o1", "date": "2026-01-01"}}},
        ]
        with patch.object(cc, '_api_get', return_value=mock_data):
            c1 = cc.scan_repo("test/repo")
            c2 = cc.scan_repo("test/repo")
        self.assertEqual(len(c1), 1)
        self.assertEqual(len(c2), 0)
    
    def test_scan_handles_error(self):
        cc = CommitCaster("fake-token")
        with patch.object(cc, '_api_get', return_value={"error": "fail"}):
            commits = cc.scan_repo("test/repo")
        self.assertEqual(len(commits), 0)
    
    def test_post_notification_empty(self):
        cc = CommitCaster("fake-token")
        result = cc.post_notification("test/repo", [])
        self.assertIsNone(result)
    
    def test_post_notification_success(self):
        cc = CommitCaster("fake-token")
        commits = [I2ICommit(sha="abc", repo="test", message="[I2I:TELL] hi", author="o1", timestamp="", message_type="TELL")]
        with patch.object(cc, '_api_post', return_value={"html_url": "https://github.com/test/repo/issues/1"}):
            url = cc.post_notification("target/repo", commits)
        self.assertIn("github.com", url)
    
    def test_cast_empty(self):
        cc = CommitCaster("fake-token")
        with patch.object(cc, '_api_get', return_value={"error": "nope"}):
            result = cc.cast("target/repo")
        self.assertEqual(result.found_commits, 0)
        self.assertEqual(result.posted_notifications, 0)
    
    def test_cast_full_flow(self):
        cc = CommitCaster("fake-token")
        cc.watch("test/repo1")
        cc.watch("test/repo2")
        mock_data = [
            {"sha": "aaa", "commit": {"message": "[I2I:ASK] question", "author": {"name": "jc1", "date": "2026-01-01"}}},
        ]
        with patch.object(cc, '_api_get', return_value=mock_data), \
             patch.object(cc, '_api_post', return_value={"html_url": "https://github.com/target/issues/1"}):
            result = cc.cast("target/repo")
        self.assertEqual(result.scanned_repos, 2)
        self.assertGreaterEqual(result.found_commits, 1)
        self.assertEqual(result.posted_notifications, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
