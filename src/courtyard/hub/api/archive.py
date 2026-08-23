"""Archive endpoints: the archived histories (design §5.7, D20). Admin surface (D3)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from courtyard.common.models import Archive
from courtyard.hub.api.deps import get_archiver
from courtyard.hub.core.archive import Archiver

router = APIRouter(prefix="/archive", tags=["archive"])


@router.get("")
def list_archives(archiver: Annotated[Archiver, Depends(get_archiver)]) -> list[Archive]:
    """Newest first, without transcripts."""
    return archiver.list()


@router.get("/{archive_id}")
def get_archive(archive_id: UUID, archiver: Annotated[Archiver, Depends(get_archiver)]) -> Archive:
    return archiver.get(archive_id)


@router.get("/{archive_id}/export")
def export_archive(
    archive_id: UUID, archiver: Annotated[Archiver, Depends(get_archiver)]
) -> Response:
    """The whole document as a JSON download — for offline audit or safekeeping."""
    archive = archiver.get(archive_id)
    stamp = archive.archived_at.strftime("%Y%m%d-%H%M%S")
    filename = f"courtyard-{archive.agent_a_name}-{archive.agent_b_name}-{stamp}.json"
    return Response(
        content=archive.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{archive_id}", status_code=204)
def delete_archive(archive_id: UUID, archiver: Annotated[Archiver, Depends(get_archiver)]) -> None:
    archiver.delete(archive_id)
