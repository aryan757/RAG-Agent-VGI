# main.py
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from bson import ObjectId
import os
import shutil
import time
from datetime import datetime
import requests

# ─── Import our helpers ───────────────────────────────────────────────
from utils import (
    upload_document_to_knowledge_base,
    list_knowledge_base_files,
    delete_document_from_knowledge_base,
    ask_question_to_knowledge_base,
    save_conversation,
    save_chat_turn,
    delete_conversation_history,
    history_collection,
)

app = FastAPI(
    title="RAG Knowledge Base API",
    description="Upload PDFs → GCP → MongoDB → Ask questions via Gemini File Search",
    version="1.0.0"
)

# ─── CORS (required when frontend runs on a different origin) ───────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
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
            "GET  /history         — View full Q&A conversation history",
            "DELETE /history/{id}  — Delete a history entry",
            "POST /save-chat-turn  — Save a chat turn (pdf or database) from ai-agent-hub",
            "GET  /chat-history    — View unified chat history (optional: ?conversation_id=)",
            "GET  /conversations   — List conversations for sidebar",
            "DELETE /delete/{id}   — Delete a document",
            "GET  /knowledgebase   — Call ElevenLabs knowledge-base API",
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


class HistoryEntry(BaseModel):
    id: str
    question: str
    answer: str
    source: str                          # "kb-ask" or "upload-and-ask"
    file_ids: Optional[List[str]] = []
    file_urls: Optional[List[str]] = []
    search_all: bool = False
    selected_documents_count: int
    asked_at: float
    asked_at_human: Optional[str] = None


class SaveChatTurnRequest(BaseModel):
    question: str
    answer: str
    source: str                           # "pdf" | "database" (or "kb-ask" | "upload-and-ask" | "database")
    conversation_id: Optional[str] = None
    chat_id: Optional[str] = None


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
        answer = ask_question_to_knowledge_base(question, file_ids=[uploaded_id], source="upload-and-ask")
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



@app.get("/history", response_model=Dict[str, List[HistoryEntry]])
async def get_history(limit: int = 50):
    """
    Return the full Q&A conversation history, newest first.

    Query params:
    - 'limit': max number of entries to return (default 50)
    """
    try:
        entries = list(
            history_collection.find()
            .sort("asked_at", -1)
            .limit(limit)
        )
        result = []
        for e in entries:
            result.append(HistoryEntry(
                id=str(e["_id"]),
                question=e.get("question", ""),
                answer=e.get("answer", ""),
                source=e.get("source", "unknown"),
                file_ids=e.get("file_ids", []),
                file_urls=e.get("file_urls", []),
                search_all=e.get("search_all", False),
                selected_documents_count=e.get("selected_documents_count", 0),
                asked_at=e.get("asked_at", 0.0),
                asked_at_human=e.get("asked_at_human"),
            ))
        return {"history": result}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to fetch history: {str(e)}")


@app.post("/save-chat-turn")
async def save_chat_turn_endpoint(body: SaveChatTurnRequest):
    """
    Save a single chat turn from ai-agent-hub (called after every response).
    Stores both PDF and database chat turns in chat_history for unified history.
    """
    try:
        entry_id = save_chat_turn(
            question=body.question,
            answer=body.answer,
            source=body.source,
            conversation_id=body.conversation_id,
            chat_id=body.chat_id,
        )
        return {"status": "saved", "id": entry_id}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to save chat turn: {str(e)}")


@app.get("/chat-history", response_model=Dict[str, List[Dict[str, Any]]])
async def get_chat_history(
    limit: int = 100,
    source: Optional[str] = None,
    conversation_id: Optional[str] = None,
):
    """
    Return unified chat history (pdf + database), newest first.
    Query params: limit (default 100), source (optional), conversation_id (optional: messages for one conversation).
    """
    try:
        from utils import chat_history_collection
        q = {}
        if source:
            q["source"] = source
        if conversation_id:
            q["conversation_id"] = conversation_id
        order = 1 if conversation_id else -1
        entries = list(
            chat_history_collection.find(q).sort("asked_at", order).limit(limit)
        )
        result = []
        for e in entries:
            result.append({
                "id": str(e["_id"]),
                "question": e.get("question", ""),
                "answer": e.get("answer", ""),
                "source": e.get("source", ""),
                "conversation_id": e.get("conversation_id", ""),
                "chat_id": e.get("chat_id", ""),
                "asked_at": e.get("asked_at", 0.0),
                "asked_at_human": e.get("asked_at_human"),
            })
        return {"chat_history": result}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to fetch chat history: {str(e)}")


@app.get("/conversations", response_model=Dict[str, List[Dict[str, Any]]])
async def get_conversations(limit: int = 50):
    """
    Return list of conversations for sidebar (grouped from chat_history by conversation_id).
    Each item: id (conversation_id), title (first question), preview (last exchange), timestamp, message_count.
    """
    try:
        from utils import chat_history_collection
        pipeline = [
            {"$match": {"conversation_id": {"$exists": True, "$ne": ""}}},
            {"$sort": {"asked_at": 1}},
            {
                "$group": {
                    "_id": "$conversation_id",
                    "first_question": {"$first": "$question"},
                    "last_question": {"$last": "$question"},
                    "last_answer": {"$last": "$answer"},
                    "timestamp": {"$max": "$asked_at"},
                    "message_count": {"$sum": 1},
                }
            },
            {"$sort": {"timestamp": -1}},
            {"$limit": limit},
        ]
        cursor = chat_history_collection.aggregate(pipeline)
        result = []
        for row in cursor:
            title = (row.get("first_question") or "").strip()
            if len(title) > 35:
                title = title[:35] + "…"
            if not title:
                title = "New chat"
            last_q = (row.get("last_question") or "").strip()
            last_a = (row.get("last_answer") or "").strip()
            preview = last_a if last_a else "You: " + (last_q[:37] + "…" if len(last_q) > 37 else last_q)
            if len(preview) > 45:
                preview = preview[:45] + "…"
            result.append({
                "id": row["_id"],
                "title": title,
                "preview": preview,
                "timestamp": row.get("timestamp", 0),
                "message_count": row.get("message_count", 0),
            })
        return {"conversations": result}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to fetch conversations: {str(e)}")


@app.delete("/history/{entry_id}")
async def delete_history_entry(entry_id: str):
    """
    Delete a single conversation history entry by its MongoDB ID.
    Use the 'id' returned from GET /history.
    """
    try:
        result = history_collection.delete_one({"_id": ObjectId(entry_id)})
        if result.deleted_count == 0:
            raise HTTPException(404, detail=f"History entry '{entry_id}' not found")
        return {"status": "deleted", "id": entry_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to delete history entry: {str(e)}")


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """
    Delete a full conversation (all turns) from chat_history by conversation_id.
    """
    try:
        count = delete_conversation_history(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id, "deleted_count": count}
    except Exception as e:
        raise HTTPException(500, detail=f"Failed to delete conversation: {str(e)}")


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


@app.get("/knowledgebase")
async def get_knowledgebase():
    """
    Call ElevenLabs knowledge-base API and return response.
    """
    url = "https://api.elevenlabs.io/v1/convai/knowledge-base?page_size=50"
    headers = {
        'xi-api-key': 'sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13'
    }
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        # Only return required fields and convert unix timestamps to ISO format 
        # so the browser can easily parse it and display it in the user's local timezone
        formatted_docs = []
        for doc in data.get("documents", []):
            metadata = doc.get("metadata", {})
            created_at_unix = metadata.get("created_at_unix_secs")
            updated_at_unix = metadata.get("last_updated_at_unix_secs")
            
            # Convert to ISO 8601 strings indicating UTC (Z)
            created_at_iso = datetime.utcfromtimestamp(created_at_unix).isoformat() + "Z" if created_at_unix else None
            updated_at_iso = datetime.utcfromtimestamp(updated_at_unix).isoformat() + "Z" if updated_at_unix else None
            
            # Map necessary fields
            doc_type = doc.get("type")
            doc_url = doc.get("url") if doc_type == "url" else "no url"
            
            formatted_docs.append({
                "id": doc.get("id"),
                "name": doc.get("name"),
                "type": doc_type,
                "size_bytes": metadata.get("size_bytes"),
                "url": doc_url,
                "created_at": created_at_iso,
                "updated_at": updated_at_iso
            })
            
        return {"documents": formatted_docs, "has_more": data.get("has_more", False)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch knowledge base: {str(e)}")