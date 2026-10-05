"""Fast owned-tree accounting; keeps memory polling independent of slow paths."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat


def disk_resources(owned_root: Path) -> dict:
    root = owned_root.resolve()
    pending = [str(root)]
    size = 0
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                    raise RuntimeError('Research tree contains a symlink or reparse point')
                if stat.S_ISDIR(info.st_mode):
                    pending.append(entry.path)
                elif stat.S_ISREG(info.st_mode):
                    size += info.st_size
    return {'free_bytes': shutil.disk_usage(root).free, 'logical_research_bytes': size}
