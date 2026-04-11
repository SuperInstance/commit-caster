# Commit Caster — I2I Notification System

Posts notifications when I2I-prefixed commits land on watched repos.

## How It Works

1. Scans watched repos for commits with `[I2I:...]` prefix
2. Deduplicates by SHA (won't re-notify)
3. Posts aggregate notification as GitHub issue on target repo
4. Can run as GitHub Action (every 15 min) or standalone CLI

## I2I Message Types

- `[I2I:TELL]` — broadcast information
- `[I2I:ASK]` — ask a question
- `[I2I:BOTTLE]` — leave a message-in-a-bottle
- `[I2I:BEACON]` — announce presence/activity
- `[I2I:CLAIM]` — claim a fence board task
- `[I2I:COMPLETE]` — mark fence board task done

## Usage

```python
from cast import CommitCaster

cc = CommitCaster(github_token)
cc.watch("SuperInstance/oracle1-vessel")
cc.watch("Lucineer/JetsonClaw1-vessel")

result = cc.cast(target_repo="SuperInstance/fleet-discovery")
print(f"Found {result.found_commits} I2I commits")
```

## GitHub Action

Includes `.github/workflows/cast.yml` for automated 15-minute polling.

10 tests passing.
