import os
import requests
import mimetypes
from datetime import datetime

def upload_to_elevenlabs_kb(local_path: str, original_filename: str):
    """
    Upload a file to the ElevenLabs Knowledge Base.
    """
    url = "https://api.elevenlabs.io/v1/convai/knowledge-base"
    api_key = os.environ.get("ELEVENLABS_API_KEY", "sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13")
    
    headers = {
        "xi-api-key": api_key
    }
    
    try:
        mime_type, _ = mimetypes.guess_type(original_filename)
        if mime_type is None:
            mime_type = "application/octet-stream"

        with open(local_path, "rb") as f:
            files = {
                "file": (original_filename, f, mime_type)
            }
            data = {
                "name": original_filename
            }
            response = requests.post(url, headers=headers, data=data, files=files)
            response.raise_for_status()
            print(f"Successfully uploaded {original_filename} to ElevenLabs: {response.json()}")
            return response.json()
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error uploading to ElevenLabs KB: {e}")
        if e.response is not None:
            print(f"ElevenLabs Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"Error uploading to ElevenLabs KB: {e}")
        # We don't bubble the error so the main Gemini upload still succeeds
        return None

def get_elevenlabs_knowledgebase():
    """
    Call ElevenLabs knowledge-base API and format the response.
    """
    url = "https://api.elevenlabs.io/v1/convai/knowledge-base?page_size=50"
    api_key = os.environ.get("ELEVENLABS_API_KEY", "sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13")
    headers = {
        'xi-api-key': api_key
    }
    
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

def attach_document_to_agent(agent_id: str, document_id: str, document_name: str):
    """
    Fetch the agent, append the document to its knowledge base, and PATCH it back.
    """
    url = f"https://api.elevenlabs.io/v1/convai/agents/{agent_id}"
    api_key = os.environ.get("ELEVENLABS_API_KEY", "sk_6dd232cd750990a82f85392f4bd653a8b408b5221d6b1d13")
    headers = {
        'xi-api-key': api_key,
        'Content-Type': 'application/json'
    }
    
    try:
        # 1. GET agent config
        response = requests.get(url, headers={'xi-api-key': api_key})
        response.raise_for_status()
        agent_data = response.json()
        
        # Extract the prompt object safely
        conversation_config = agent_data.get("conversation_config", {})
        agent_config = conversation_config.get("agent", {})
        prompt_config = agent_config.get("prompt", {})
        
        kb_list = prompt_config.get("knowledge_base", [])
        
        # Check if document already exists
        if any(doc.get("id") == document_id for doc in kb_list):
            print(f"Document {document_id} already attached to agent {agent_id}")
            return True
        
        # Append new doc
        kb_list.append({
            "type": "file",
            "name": document_name,
            "id": document_id
        })
        
        # Put it back
        prompt_config["knowledge_base"] = kb_list
        
        # Prepare PATCH payload. It's safe to just send the whole prompt block back.
        patch_payload = {
            "conversation_config": {
                "agent": {
                    "prompt": prompt_config
                }
            }
        }
        
        # 2. PATCH agent config
        patch_response = requests.patch(url, headers=headers, json=patch_payload)
        patch_response.raise_for_status()
        print(f"Successfully attached document '{document_name}' to agent {agent_id}")
        return patch_response.json()
        
    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error attaching document to agent {agent_id}: {e}")
        if e.response is not None:
            print(f"Response: {e.response.text}")
        return None
    except Exception as e:
        print(f"Error attaching document to agent {agent_id}: {e}")
        return None
