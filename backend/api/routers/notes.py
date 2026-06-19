from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db, Note
from models import NoteOut, NoteSyncRequest, NoteSyncResponse
from auth import require_session

router = APIRouter(prefix="/api/notes", tags=["notes"], dependencies=[Depends(require_session)])


@router.get("", response_model=List[NoteOut])
def get_notes(db: Session = Depends(get_db)):
    """Get all notes without the full content_md."""
    notes = db.execute(
        select(Note.id, Note.filename, Note.title, Note.bibtex_key, Note.theme, Note.cluster, Note.last_modified, Note.created_at)
        .order_by(Note.last_modified.desc())
    ).all()
    # Pydantic will map this tuple list into NoteOut objects. Since content_md is optional, it will be None.
    return [NoteOut.model_validate(n) for n in notes]


@router.get("/{note_id}", response_model=NoteOut)
def get_note(note_id: int, db: Session = Depends(get_db)):
    """Get a specific note by ID including its full content."""
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.post("/sync", response_model=NoteSyncResponse)
def sync_notes(payload: NoteSyncRequest, db: Session = Depends(get_db)):
    """Sync notes from local filesystem."""
    added = 0
    updated = 0
    
    existing_notes = {n.filename: n for n in db.query(Note).all()}
    current_filenames = set()

    for item in payload.notes:
        current_filenames.add(item.filename)
        if item.filename in existing_notes:
            note = existing_notes[item.filename]
            note.title = item.title
            note.bibtex_key = item.bibtex_key
            note.theme = item.theme
            note.cluster = item.cluster
            note.content_md = item.content_md
            note.last_modified = item.last_modified
            updated += 1
        else:
            new_note = Note(
                filename=item.filename,
                title=item.title,
                bibtex_key=item.bibtex_key,
                theme=item.theme,
                cluster=item.cluster,
                content_md=item.content_md,
                last_modified=item.last_modified
            )
            db.add(new_note)
            added += 1

    deleted = 0
    for filename, note in existing_notes.items():
        if filename not in current_filenames:
            db.delete(note)
            deleted += 1

    db.commit()
    
    return NoteSyncResponse(added=added, updated=updated, deleted=deleted)
