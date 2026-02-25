# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import os
import shutil
import time
from datetime import datetime

# ─── Import our helpers ───────────────────────────────────────────────
from utils import (
    upload_document_to_knowledge_base,
    list_knowledge_base_files,
    delete_document_from_knowledge_base,
    ask_question_to_knowledge_base,
)

app = FastAPI(
    title="RAG Knowledge Base API",
    description="Upload PDFs → GCP → MongoDB → Ask questions via Gemini File Search",
    version="1.0.0"
)


# ─── Root ──────────────────────────────────────────────────────────────
@app.get("/")
def read_root():
    return {
        "message": "RAG Knowledge Base API is running",
        "time": datetime.utcnow().isoformat(),
        "endpoints": [
            "POST /upload          — Upload a PDF → GCP → MongoDB",
            "GET  /list            — List all documents (id + gcp_link)",
            "POST /upload-and-ask  — Upload docs + immediately ask a question",
            "POST /kb-ask          — Ask a question using existing KB docs",
            "DELETE /delete/{id}   — Delete a document",
        ]
    }


# ─── Pydantic Models ───────────────────────────────────────────────────

class UploadResponse(BaseModel):
    status: str
    original_filename: str
    gcp_link: str
    id: str


class FileInfo(BaseModel):
    id: str
    original_filename: str
    display_name: str
    gcp_link: Optional[str] = None   # Optional: legacy docs may not have this
    uploaded_at: float
    uploaded_at_human: Optional[str] = None




class AskResponse(BaseModel):
    question: str
    answer: str
    selected_documents_count: int


# ─── Endpoints ─────────────────────────────────────────────────────────

@app.post("/upload", response_model=UploadResponse)
async def upload_to_kb(
    file: UploadFile = File(...),
    display_name: Optional[str] = Form(None),
):
    """
    Upload a PDF → GCP Storage → Gemini File Search Store → MongoDB.
    Returns the GCP URL and MongoDB document ID.
    """
    temp_path = f"temp_{int(time.time())}_{file.filename}"
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = upload_document_to_knowledge_base(
            local_path=temp_path,
            original_filename=file.filename,
            display_name=display_name or file.filename
        )

        return UploadResponse(
            status="success",
            original_filename=result["original_filename"],
            gcp_link=result["gcp_link"],
            id=result["id"]
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.get("/list", response_model=Dict[str, List[FileInfo]])
async def list_files():
    """
    List all uploaded documents with their MongoDB IDs and GCP links.
    Use the returned 'id' or 'gcp_link' in /kb-ask to filter documents.
    """
    try:
        files = list_knowledge_base_files()
        formatted_files = []
        for f in files:
            if "uploaded_at" in f and f["uploaded_at"]:
                f["uploaded_at_human"] = datetime.utcfromtimestamp(
                    f["uploaded_at"]
                ).strftime("%Y-%m-%d %H:%M:%S UTC")
            # Ensure required fields exist before returning
            if not f.get("original_filename"):
                f["original_filename"] = "unknown"
            if not f.get("display_name"):
                f["display_name"] = f.get("original_filename", "unknown")
            if not f.get("uploaded_at"):
                f["uploaded_at"] = 0.0
            formatted_files.append(f)

        return {"files": formatted_files}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@app.post("/upload-and-ask", response_model=AskResponse)
async def upload_and_ask(
    question: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Upload a document → GCP → MongoDB → immediately ask a question about it.

    Use multipart/form-data:
    - 'question': your question (form field)
    - 'file': the PDF/text file to upload and query
    """
    if not question.strip():
        raise HTTPException(400, "Question cannot be empty")

    temp_path = f"temp_{int(time.time())}_{file.filename}"
    try:
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        result = upload_document_to_knowledge_base(
            local_path=temp_path,
            original_filename=file.filename,
            display_name=file.filename
        )
        uploaded_id = result["id"]
    except Exception as e:
        raise HTTPException(500, detail=f"Upload failed for {file.filename}: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    # Ask using ONLY this uploaded file
    try:
        answer = ask_question_to_knowledge_base(question, file_ids=[uploaded_id])
        return AskResponse(
            question=question,
            answer=answer,
            selected_documents_count=1
        )
    except Exception as e:
        raise HTTPException(500, detail=f"RAG query failed: {str(e)}")


@app.post("/kb-ask", response_model=AskResponse)
async def kb_ask(
    question: str = Form(...),
    file_ids: Optional[str] = Form(None, description="Comma-separated MongoDB IDs from /list. Use 'all' to search ALL documents in the knowledge base."),
    file_urls: Optional[str] = Form(None, description="Comma-separated GCP links from /list (e.g. url1,url2)"),
):
    """
    Ask a question against documents in the knowledge base.

    Use multipart/form-data:
    - 'question'   : your question
    - 'file_ids'   : (optional) comma-separated MongoDB IDs | use 'all' for global search
    - 'file_urls'  : (optional) comma-separated GCP links from /list
    - Leave both empty → automatically uses your MOST RECENTLY uploaded document
    """
    if not question.strip():
        raise HTTPException(400, "Question cannot be empty")

    # Special keyword: file_ids=all → global search across entire KB
    search_all = bool(file_ids and file_ids.strip().lower() == "all")

    # Parse comma-separated strings into lists (skip if "all")
    ids_list = [i.strip() for i in file_ids.split(",") if i.strip()] if (file_ids and not search_all) else None
    urls_list = [u.strip() for u in file_urls.split(",") if u.strip()] if file_urls else None

    try:
        answer = ask_question_to_knowledge_base(
            question=question,
            file_ids=ids_list,
            file_urls=urls_list,
            search_all=search_all,
        )

        if search_all:
            count = len(list_knowledge_base_files())
        elif ids_list:
            count = len(ids_list)
        elif urls_list:
            count = len(urls_list)
        else:
            count = 1  # defaulted to most recent upload

        return AskResponse(
            question=question,
            answer=answer,
            selected_documents_count=count
        )
    except Exception as e:
        raise HTTPException(500, detail=f"RAG query failed: {str(e)}")


@app.delete("/delete/{doc_id}")
async def delete_file(doc_id: str):
    """
    Delete a document from MongoDB (and best-effort from GCP + Gemini).
    Use the 'id' returned from /upload or /list.
    """
    success = delete_document_from_knowledge_base(doc_id)
    if success:
        return {"status": "deleted", "id": doc_id}
    else:
        raise HTTPException(404, detail=f"Document with id '{doc_id}' not found")