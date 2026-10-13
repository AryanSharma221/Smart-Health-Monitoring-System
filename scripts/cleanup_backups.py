"""
Automated Backup Retention and Pruning Utility.

Safety Invariants:
- Strictly confines pruning actions to designated backup root directories.
- Prohibits path traversal and prevents deletion of arbitrary files.
- Automatically pairs backup archives with their companion `.sha256` and `.manifest.json` files.
- Defaults to safe dry-run mode unless `--execute` is explicitly specified.
- Maintains a minimum safety threshold of the N newest backup sets.

Usage:
    python -m scripts.cleanup_backups [--backup-dir DIR] [--keep-count N] [--keep-days DAYS] [--execute]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup_backups")

DEFAULT_BACKUP_DIRS = [
    Path("backups/mysql"),
    Path("backups/mongodb"),
]

ALLOWED_PRIMARY_EXTENSIONS = {".gz", ".sql", ".tar", ".archive"}


def is_safe_backup_artifact(file_path: Path, base_dir: Path) -> bool:
    """Verify that file is safely inside base_dir and matches backup patterns."""
    try:
        resolved_file = file_path.resolve()
        resolved_base = base_dir.resolve()
        # Ensure file is strictly inside base_dir
        resolved_file.relative_to(resolved_base)
    except ValueError:
        return False

    name = file_path.name.lower()
    return name.startswith("mysql_") or name.startswith("mongodb_")


def group_backup_artifacts(backup_dir: Path) -> List[Dict[str, Any]]:
    """
    Scan directory and group primary backup files with their companions (.sha256, .manifest.json).
    Returns list of backup sets sorted by modification time (newest first).
    """
    if not backup_dir.is_dir():
        return []

    # Find primary archives
    primary_files = []
    for item in backup_dir.iterdir():
        if not item.is_file() or not is_safe_backup_artifact(item, backup_dir):
            continue
        if item.name.endswith(".sha256") or item.name.endswith(".manifest.json"):
            continue
        primary_files.append(item)

    # Sort newest first
    primary_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    backup_sets = []
    for p in primary_files:
        mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        companions = []
        sha_file = backup_dir / f"{p.name}.sha256"
        if sha_file.is_file():
            companions.append(sha_file)
        manifest_file = backup_dir / f"{p.name}.manifest.json"
        if manifest_file.is_file():
            companions.append(manifest_file)

        backup_sets.append({
            "primary": p,
            "companions": companions,
            "modified_utc": mtime.isoformat(),
            "mtime_timestamp": p.stat().st_mtime,
            "size_bytes": p.stat().st_size + sum(c.stat().st_size for c in companions),
        })

    return backup_sets


def prune_backups(
    backup_dir: Path,
    keep_count: int = 7,
    keep_days: Optional[int] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate and prune old backup artifacts based on count and retention window.

    Retention Policy:
    - Always retains at least the newest `keep_count` backup sets (guaranteed floor).
    - If `keep_days` is specified: additionally retains any sets within the last `keep_days` days.
    - Sets beyond `keep_count` that are older than `keep_days` (or all sets beyond `keep_count` if keep_days is None) are pruned.
    """
    cutoff_timestamp = None
    if keep_days is not None:
        now = datetime.now(timezone.utc)
        cutoff_time = now - timedelta(days=keep_days)
        cutoff_timestamp = cutoff_time.timestamp()

    backup_sets = group_backup_artifacts(backup_dir)

    retained: List[str] = []
    to_delete: List[Path] = []

    for idx, b_set in enumerate(backup_sets):
        primary_path: Path = b_set["primary"]
        is_guaranteed_count = idx < keep_count
        is_within_days = (
            cutoff_timestamp is not None
            and b_set["mtime_timestamp"] >= cutoff_timestamp
        )

        if is_guaranteed_count or is_within_days:
            retained.append(primary_path.name)
        else:
            to_delete.append(primary_path)
            to_delete.extend(b_set["companions"])

    # Execute deletion or simulate
    deleted_files: List[str] = []
    freed_bytes = 0

    for f in to_delete:
        if not is_safe_backup_artifact(f, backup_dir):
            logger.warning("Skipping unsafe file candidate: %s", f)
            continue

        f_size = f.stat().st_size if f.exists() else 0
        if not dry_run:
            try:
                f.unlink()
                deleted_files.append(f.name)
                freed_bytes += f_size
                logger.info("Deleted expired backup artifact: %s", f.name)
            except Exception as exc:
                logger.error("Failed to delete %s: %s", f.name, exc)
        else:
            deleted_files.append(f.name)
            freed_bytes += f_size
            logger.info("[DRY-RUN] Would delete: %s (%d bytes)", f.name, f_size)

    return {
        "backup_directory": str(backup_dir),
        "dry_run": dry_run,
        "total_sets_found": len(backup_sets),
        "retained_sets_count": len(retained),
        "retained_files": retained,
        "pruned_files_count": len(deleted_files),
        "pruned_files": deleted_files,
        "freed_bytes": freed_bytes,
    }


def main() -> None:
    """CLI entrypoint for backup cleanup utility."""
    parser = argparse.ArgumentParser(description="Automated Backup Retention and Pruning Utility")
    parser.add_argument("--backup-dir", type=Path, default=None, help="Directory to prune (defaults to all standard dirs)")
    parser.add_argument("--keep-count", type=int, default=7, help="Minimum number of newest backup sets to keep")
    parser.add_argument("--keep-days", type=int, default=30, help="Retention period in days")
    parser.add_argument("--execute", action="store_true", help="Execute real deletion (default is dry-run)")
    args = parser.parse_args()

    dirs_to_process = [args.backup_dir] if args.backup_dir else DEFAULT_BACKUP_DIRS
    dry_run = not args.execute

    overall_results = []
    for d in dirs_to_process:
        if d.is_dir():
            res = prune_backups(backup_dir=d, keep_count=args.keep_count, keep_days=args.keep_days, dry_run=dry_run)
            overall_results.append(res)
        else:
            overall_results.append({
                "backup_directory": str(d),
                "status": "directory_not_found",
            })

    print(json.dumps(overall_results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
