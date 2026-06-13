"""Async facade over ``write_patch``.

``LatexEditService.handle_message`` awaits ``self.writer.apply(...)``;
the underlying ``write_patch`` is synchronous, so we offload it to a
thread to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from .surgical_writer import Patch, write_patch


class Writer:
    async def apply(self, tex_path: str | Path, patch: Patch) -> None:
        await asyncio.to_thread(write_patch, tex_path, patch)
