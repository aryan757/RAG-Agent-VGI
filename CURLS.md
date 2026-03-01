# RAG-Agent-VGI — cURL examples

Use `BASE_URL=http://localhost:8000` (or your server). Replace `$BASE_URL` in the commands below.

---

## 1. Root (health / endpoints list)

```bash
curl -s "$BASE_URL/"
```

---

## 2. Upload a document

```bash
curl -X POST "$BASE_URL/upload" \
  -F "file=@/path/to/your/document.pdf" \
  -F "display_name=My Document"
```

---

## 3. List all documents

```bash
curl -s "$BASE_URL/list"
```

---

## 4. Upload and ask (one shot)

```bash
curl -X POST "$BASE_URL/upload-and-ask" \
  -F "question=What is this document about?" \
  -F "file=@/path/to/your/document.pdf"
```

---

## 5. Ask knowledge base (kb-ask)

**Default (most recent document):**
```bash
curl -X POST "$BASE_URL/kb-ask" \
  -F "question=What is this document about?"
```

**Search all documents:**
```bash
curl -X POST "$BASE_URL/kb-ask" \
  -F "question=Summarize everything" \
  -F "file_ids=all"
```

**Specific document(s) by ID:**
```bash
curl -X POST "$BASE_URL/kb-ask" \
  -F "question=What is the project codename?" \
  -F "file_ids=699dc9606f0d05f522ccaac2"
```

**Specific document(s) by GCP URL:**
```bash
curl -X POST "$BASE_URL/kb-ask" \
  -F "question=Who wrote this?" \
  -F "file_urls=https://storage.googleapis.com/your-bucket/kb/..."
```

---

## 6. Conversation history (RAG Q&A only)

```bash
curl -s "$BASE_URL/history?limit=50"
```

---

## 7. Delete a conversation history entry

```bash
curl -X DELETE "$BASE_URL/history/ENTRY_MONGODB_ID"
```

---

## 8. Save a chat turn (from ai-agent-hub)

```bash
curl -X POST "$BASE_URL/save-chat-turn" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the revenue?",
    "answer": "The revenue for Q1 was...",
    "source": "database",
    "conversation_id": "abc-123",
    "chat_id": "xyz-456"
  }'
```

`source` can be `"pdf"` or `"database"`. `conversation_id` and `chat_id` are optional.

---

## 9. Get chat history (unified PDF + database)

**All chat history (newest first):**
```bash
curl -s "$BASE_URL/chat-history?limit=100"
```

**Filter by source:**
```bash
curl -s "$BASE_URL/chat-history?limit=100&source=pdf"
curl -s "$BASE_URL/chat-history?limit=100&source=database"
```

**One conversation’s messages:**
```bash
curl -s "$BASE_URL/chat-history?conversation_id=YOUR_CONVERSATION_ID&limit=100"
```

---

## 10. List conversations (for sidebar)

```bash
curl -s "$BASE_URL/conversations?limit=50"
```

---

## 11. Delete a document from the knowledge base

```bash
curl -X DELETE "$BASE_URL/delete/DOC_MONGODB_ID"
```

Use the document `id` from `/list`.

---

## One-liner with BASE_URL set

```bash
BASE_URL=http://localhost:8000

# Quick checks
curl -s "$BASE_URL/"
curl -s "$BASE_URL/list"
curl -s "$BASE_URL/conversations"
curl -s "$BASE_URL/chat-history?limit=10"
```
