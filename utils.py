# utils.py
import os
import time
import shutil
import mimetypes
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

from google import genai
from google.genai import types
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from google.cloud import storage
from bson import ObjectId

load_dotenv()

# ─── Gemini setup ────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY)

STORE_NAME = os.getenv("FILE_SEARCH_STORE_NAME", "my-rag-knowledge-base-2026").strip()
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.0-flash").strip()

# ─── MongoDB Atlas setup ─────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = MongoClient(
    MONGO_URI,
    server_api=ServerApi(version="1", strict=True, deprecation_errors=True)
)
db = mongo_client["rag_app"]
kb_collection = db["knowledge_base_files"]

# ─── GCP Storage setup ──────────────────────────────────────────
GCP_PROJECT = os.getenv("GCP_PROJECT")
GCP_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "").strip()

storage_client = storage.Client(project=GCP_PROJECT)


# ─── GCP Helpers ────────────────────────────────────────────────

def create_bucket_if_not_exists():
    """Get or create the GCP bucket."""
    try:
        bucket = storage_client.get_bucket(GCP_BUCKET_NAME)
        return bucket
    except Exception:
        print(f"[GCS] Bucket '{GCP_BUCKET_NAME}' not found — creating...")
        bucket = storage_client.create_bucket(GCP_BUCKET_NAME)
        return bucket


def upload_to_gcs(local_path: str, blob_name: str) -> str:
    """Upload a local file to GCS and return its public HTTPS URL."""
    bucket = create_bucket_if_not_exists()
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)
    return f"https://storage.googleapis.com/{GCP_BUCKET_NAME}/{blob_name}"


# ─── File Search Store Helpers ──────────────────────────────────

def ensure_file_search_store_exists() -> str:
    """
    Return the resource name of the File Search Store.
    Tries to find an existing store matching STORE_NAME, creates one if missing.
    """
    display_name_target = "RAG Knowledge Base 2026"
    try:
        stores = list(client.file_search_stores.list())
        for s in stores:
            if s.display_name == display_name_target:
                print(f"[Store] Using existing store: {s.name}")
                return s.name

        # Not found — create a new one
        store = client.file_search_stores.create(
            config=types.CreateFileSearchStoreConfig(
                display_name=display_name_target
            )
        )
        print(f"[Store] Created new store: {store.name}")
        return store.name
    except Exception as e:
        print(f"[Store] Could not ensure store exists: {e}")
        # Fallback: return the configured name directly (might be a resource name)
        return STORE_NAME


# ─── Core Operations ────────────────────────────────────────────

def upload_document_to_knowledge_base(
    local_path: str,
    original_filename: str,
    display_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Upload pipeline:
      1. Upload file to GCP Storage → get public URL
      2. Upload file to Gemini File API (for content extraction)
      3. Import into Gemini File Search Store (for RAG filtering)
      4. Save metadata to MongoDB → return doc _id as string
    """
    if not display_name:
        display_name = original_filename

    # ── Step 1: GCP Upload ─────────────────────────────────────
    blob_name = f"kb/{int(time.time())}_{original_filename}"
    gcp_link = upload_to_gcs(local_path, blob_name)
    print(f"[GCS] Uploaded to: {gcp_link}")

    # ── Step 2 & 3: Gemini File API + File Search Store ────────
    mime_type, _ = mimetypes.guess_type(local_path)
    if not mime_type:
        if original_filename.lower().endswith(".pdf"):
            mime_type = "application/pdf"
        elif original_filename.lower().endswith(".txt"):
            mime_type = "text/plain"
        else:
            mime_type = "application/octet-stream"

    # Upload to File API first
    uploaded_file = client.files.upload(
        file=local_path,
        config=types.UploadFileConfig(
            display_name=display_name,
            mime_type=mime_type
        )
    )
    print(f"[Gemini] Uploaded file: {uploaded_file.name}")

    # Import into the File Search Store
    try:
        upload_op = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=ACTIVE_STORE_NAME,
            file=local_path,
            config=types.UploadToFileSearchStoreConfig(
                display_name=display_name,
            )
        )

        # Poll until the operation is done
        max_wait = 60  # seconds
        waited = 0
        while not upload_op.done:
            time.sleep(2)
            waited += 2
            upload_op = client.operations.get(upload_op)
            if waited >= max_wait:
                print("[Store] Timed out waiting for store import — continuing anyway.")
                break

        print(f"[Store] Import operation done: {upload_op.done}")
    except Exception as e:
        print(f"[Store] Warning: Could not import into File Search Store: {e}")
        # Non-fatal — we still have the GCP link for reference

    # ── Step 4: MongoDB ─────────────────────────────────────────
    doc = {
        "original_filename": original_filename,
        "display_name": display_name,
        "gcp_link": gcp_link,
        "gemini_file_name": uploaded_file.name,   # save for potential cleanup
        "uploaded_at": time.time(),
        "metadata": metadata or {},
        "status": "active"
    }
    result = kb_collection.insert_one(doc)
    doc_id = str(result.inserted_id)
    print(f"[MongoDB] Saved metadata with id: {doc_id}")

    return {
        "original_filename": original_filename,
        "gcp_link": gcp_link,
        "id": doc_id
    }


def list_knowledge_base_files() -> List[Dict[str, Any]]:
    """
    Return all active documents from MongoDB.
    Each doc has: id, original_filename, display_name, gcp_link, uploaded_at
    """
    docs = list(kb_collection.find(
        {"status": "active"},
        {
            "_id": 1,
            "original_filename": 1,
            "display_name": 1,
            "uploaded_at": 1,
            "gcp_link": 1
        }
    ))
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return docs


def delete_document_from_knowledge_base(doc_id_or_filename: str) -> bool:
    """
    Delete a document record from MongoDB, and best-effort cleanup from GCS & Gemini.
    Accepts either a MongoDB ObjectId string or original_filename.
    """
    # Find the doc
    try:
        query = {"_id": ObjectId(doc_id_or_filename)}
    except Exception:
        query = {"original_filename": doc_id_or_filename}

    doc = kb_collection.find_one(query)
    if not doc:
        return False

    # Best-effort: delete from Gemini Files API
    if "gemini_file_name" in doc:
        try:
            client.files.delete(name=doc["gemini_file_name"])
            print(f"[Gemini] Deleted file: {doc['gemini_file_name']}")
        except Exception as e:
            print(f"[Gemini] Could not delete file: {e}")

    # Best-effort: delete from GCS
    if "gcp_link" in doc:
        try:
            blob_name = doc["gcp_link"].split(f"{GCP_BUCKET_NAME}/")[-1]
            bucket = storage_client.get_bucket(GCP_BUCKET_NAME)
            bucket.blob(blob_name).delete()
            print(f"[GCS] Deleted blob: {blob_name}")
        except Exception as e:
            print(f"[GCS] Could not delete blob: {e}")

    # Delete from MongoDB
    kb_collection.delete_one({"_id": doc["_id"]})
    print(f"[MongoDB] Deleted document: {doc['_id']}")
    return True


def ask_question_to_knowledge_base(
    question: str,
    file_ids: Optional[List[str]] = None,
    file_urls: Optional[List[str]] = None,
    search_all: bool = False,
) -> str:
    """
    Answer a question using the correct Gemini grounding strategy.

    CASE 1 - file_ids provided    → query those specific docs directly
    CASE 2 - file_urls provided   → resolve from MongoDB, query directly
    CASE 3 - search_all = True    → global FileSearch on entire store
    CASE 4 - nothing provided     → default to MOST RECENTLY uploaded doc
    """

    # CASE 1: Specific docs via MongoDB IDs
    if file_ids:
        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception as e:
            raise ValueError(f"Invalid file_id format: {e}")
        docs = list(kb_collection.find(
            {"_id": {"$in": object_ids}},
            {"gemini_file_name": 1, "original_filename": 1}
        ))
        return _ask_with_file_refs(question, docs)

    # CASE 2: Specific docs via GCP URLs
    elif file_urls:
        docs = list(kb_collection.find(
            {"gcp_link": {"$in": file_urls}},
            {"gemini_file_name": 1, "original_filename": 1}
        ))
        return _ask_with_file_refs(question, docs)

    # CASE 3: Explicit global search (file_ids="all")
    elif search_all:
        return _ask_global(question)

    # CASE 4: Default — use the most recently uploaded document
    else:
        latest = _get_latest_upload()
        if latest:
            print(f"[RAG] No filter given — defaulting to latest upload: '{latest.get('original_filename')}'")
            return _ask_with_file_refs(question, [latest])
        else:
            print("[RAG] No documents in KB — falling back to global search")
            return _ask_global(question)


def _get_latest_upload() -> Optional[dict]:
    """Return the most recently uploaded active document from MongoDB."""
    docs = list(
        kb_collection.find(
            {"status": "active", "gemini_file_name": {"$exists": True}},
            {"gemini_file_name": 1, "original_filename": 1, "uploaded_at": 1}
        ).sort("uploaded_at", -1).limit(1)
    )
    return docs[0] if docs else None


def _ask_with_file_refs(question: str, docs: list) -> str:
    """
    Pass Gemini file references directly as content parts to generate_content.
    This is the correct approach for querying SPECIFIC files.
    NOTE: Gemini File API files expire after 48 hours — if expired, user must re-upload.
    """
    file_parts = []
    for doc in docs:
        if not doc.get("gemini_file_name"):
            print(f"[RAG] Skipping '{doc.get('original_filename')}' — no gemini_file_name (legacy doc)")
            continue
        try:
            gemini_file = client.files.get(name=doc["gemini_file_name"])
            file_parts.append(
                types.Part.from_uri(
                    file_uri=gemini_file.uri,
                    mime_type=gemini_file.mime_type or "application/octet-stream"
                )
            )
            print(f"[RAG] Attached: {doc['gemini_file_name']}")
        except Exception as e:
            print(f"[RAG] Could not attach '{doc.get('gemini_file_name')}': {e}")

    if not file_parts:
        return (
            "The selected document(s) could not be retrieved from Gemini. "
            "They may be legacy docs (uploaded before this version) or may have expired (files expire after 48h). "
            "Please re-upload using /upload and use the new ID, or use /kb-ask without file_ids to search all documents."
        )

    # Build content: [file_part, ..., question_text]
    # contents = file_parts + [question]
    contents = question
    print(f"[RAG] Direct query with {len(file_parts)} file ref(s)")

    # response = client.models.generate_content(
    #     model=MODEL_ID,
    #     contents=contents,
    #     config=types.GenerateContentConfig(
    #         temperature=0.3,
    #         max_output_tokens=1500,
    #     )
    # )

    response = client.models.generate_content(
        model=MODEL_ID,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1500,
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[ACTIVE_STORE_NAME],
                    )
                )
            ]
        )
    )

    answer = (response.text or "").strip()
    if not answer:
        answer = "The model could not extract a relevant answer from the selected document(s). Try rephrasing your question."
    return answer


def _ask_global(question: str) -> str:
    """
    Global search across the entire File Search Store with no filter.
    Matches the working Colab notebook pattern exactly.
    """
    print(f"[RAG] Global search on store '{ACTIVE_STORE_NAME}'")
    response = client.models.generate_content(
        model=MODEL_ID,
        contents=question,
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=1500,
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[ACTIVE_STORE_NAME],
                    )
                )
            ]
        )
    )

    answer = (response.text or "").strip()
    if not answer:
        answer = (
            "I couldn't find relevant information in the knowledge base. "
            "Please make sure documents have been uploaded and try rephrasing your question."
        )
    return answer


# ─── Initialize the File Search Store on module load ────────────
# This runs once when FastAPI starts. Safe even if called multiple times.
ACTIVE_STORE_NAME = ensure_file_search_store_exists()
print(f"[Init] Active File Search Store: {ACTIVE_STORE_NAME}")