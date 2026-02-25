# 📚 RAG Knowledge Base API

A FastAPI-based Retrieval-Augmented Generation (RAG) system that lets you upload documents, store them in GCP and MongoDB, and ask questions using Google Gemini AI.

---

## 🧱 Architecture

```
User → FastAPI → GCP Storage (file stored)
                → Gemini File API (content indexed)
                → Gemini File Search Store (RAG grounding)
                → MongoDB Atlas (metadata saved: id, gcp_link, filename)

User → /kb-ask or /upload-and-ask → Gemini AI → Answer
```

---

## 🚀 Running the Server

```bash
# Activate virtual environment
source venv/bin/activate

# Start server (auto-reloads on file changes)
uvicorn main:app --reload --port 8000

# Swagger UI available at:
# http://localhost:8000/docs
```

---

## 📬 Postman Collection Setup

1. Open Postman → **New Collection** → Name it `RAG Agent`
2. Set a Collection Variable: `base_url` = `http://localhost:8000`
3. Add the 5 requests below

---

## 📌 Endpoints

---

### 1. `POST /upload`
**Upload a document to the knowledge base.**

Uploads to GCP Storage, indexes in Gemini, and saves metadata in MongoDB.

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `{{base_url}}/upload` |
| Body | `form-data` |

**Form fields:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `file` | File | ✅ | Select your PDF or TXT file |
| `display_name` | Text | ❌ | A friendly name (defaults to filename) |

**Response:**
```json
{
  "status": "success",
  "original_filename": "Todays_discussion.pdf",
  "gcp_link": "https://storage.googleapis.com/...",
  "id": "699dc9606f0d05f522ccaac2"
}
```
> 💾 **Save the `id` and `gcp_link`** — you'll need them for `/kb-ask`.

---

### 2. `GET /list`
**List all uploaded documents with their IDs and GCP links.**

| Setting | Value |
|---------|-------|
| Method | `GET` |
| URL | `{{base_url}}/list` |
| Body | None |

**Response:**
```json
{
  "files": [
    {
      "id": "699dc9606f0d05f522ccaac2",
      "original_filename": "Todays_discussion.pdf",
      "display_name": "Todays_discussion.pdf",
      "gcp_link": "https://storage.googleapis.com/...",
      "uploaded_at_human": "2026-02-24 15:53:04 UTC"
    }
  ]
}
```

---

### 3. `POST /upload-and-ask`
**Upload a document and immediately ask a question about it.**

Does everything in one shot: upload → index → query → answer.

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `{{base_url}}/upload-and-ask` |
| Body | `form-data` |

**Form fields:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `question` | Text | ✅ | Your question about the document |
| `file` | File | ✅ | Select your PDF or TXT file |

**Response:**
```json
{
  "question": "What is this document about?",
  "answer": "This document is about...",
  "selected_documents_count": 1
}
```

---

### 4. `POST /kb-ask`
**Ask a question using documents already in the knowledge base.**

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `{{base_url}}/kb-ask` |
| Body | `form-data` |

**Form fields:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `question` | Text | ✅ | Your question |
| `file_ids` | Text | ❌ | Comma-separated MongoDB IDs from `/list`. Use `all` to search everything. |
| `file_urls` | Text | ❌ | Comma-separated GCP links from `/list` |

**4 modes of use:**

**Mode A — Default (no filter): uses your most recently uploaded document**
```
question  →  What is this document about?
```
*(leave file_ids and file_urls empty — automatically picks the latest upload)*

**Mode B — Search ALL documents:**
```
question  →  Summarize everything
file_ids  →  all
```

**Mode C — Query specific docs by ID:**
```
question  →  What is the project codename?
file_ids  →  699dc9606f0d05f522ccaac2
```
*(copy the `id` field from `/list` response)*

**Mode D — Query specific docs by GCP URL:**
```
question   →  Who wrote this?
file_urls  →  https://storage.googleapis.com/rag-agent-docs-aryan/kb/...
```

> ℹ️ For multiple documents in Mode C or D: comma-separate values.
> `file_ids → id1,id2,id3`

---

### 5. `DELETE /delete/{id}`
**Delete a document from the knowledge base.**

Removes from MongoDB, and best-effort cleanup from GCP and Gemini.

| Setting | Value |
|---------|-------|
| Method | `DELETE` |
| URL | `{{base_url}}/delete/699dc9606f0d05f522ccaac2` |
| Body | None |

> Put the document `id` (from `/list`) directly in the URL.

**Response:**
```json
{
  "status": "deleted",
  "id": "699dc9606f0d05f522ccaac2"
}
```

---

## 🔄 Typical Workflow

```
1. POST /upload          → upload your PDF
2. GET /list             → see all docs + copy the id
3. POST /kb-ask          → just send a question — auto uses your latest upload!
4. POST /kb-ask          → pass file_ids for a specific doc, or file_ids=all for everything
5. DELETE /delete/{id}   → clean up when done
```

Or the fast route:
```
1. POST /upload-and-ask  → upload + ask in one step
2. POST /kb-ask          → ask follow-up questions (auto picks your latest upload)
```

---

## ⚠️ Important Notes

| Note | Detail |
|------|--------|
| **Default behaviour** | `/kb-ask` with no `file_ids` or `file_urls` automatically uses your **most recently uploaded document**. |
| **Search all docs** | Pass `file_ids=all` to search across your entire knowledge base. |
| **File expiry** | Gemini File API files expire after **48 hours**. Re-upload if `/kb-ask` with `file_ids` stops working on old docs. |
| **Legacy docs** | Docs uploaded before this version show `gcp_link: null` in `/list` — re-upload them to enable per-document querying. |
| **Supported formats** | PDF, TXT, MD, DOCX, PNG, JPG (any file Gemini can parse) |

---

## 🔐 Environment Variables (`.env`)

```env
GEMINI_API_KEY=...
MONGO_URI=mongodb+srv://...
GCP_PROJECT=your-gcp-project
GCP_BUCKET_NAME=your-bucket-name
FILE_SEARCH_STORE_NAME=my-knowledge-base-store
MODEL_ID=gemini-2.0-flash
```
