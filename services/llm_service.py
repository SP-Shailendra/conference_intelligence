import json
import re
import time
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL
from services.rag_service import retrieve_context
from data.knowledge import MOCK_ARCHIVE

client = Groq(api_key=GROQ_API_KEY)

# ---------------------------------------------------------
# TEXT SANITIZER (The Unicode Firewall)
# ---------------------------------------------------------
def _sanitize_text(text: str) -> str:
    """
    Cleans text to prevent strict environment ASCII codec errors.
    Replaces common smart punctuation (from PDFs/PPTXs) with standard ASCII equivalents,
    then forcefully ignores remaining unencodable characters.
    """
    if not text:
        return ""
    
    # Replace common unicode typography with safe ascii equivalents
    replacements = {
        '\u2018': "'", '\u2019': "'",   # Smart single quotes
        '\u201c': '"', '\u201d': '"',   # Smart double quotes
        '\u2013': '-', '\u2014': '-',   # En and Em dashes
        '\u2022': '*',                  # Bullet points
        '\u2026': '...',                # Ellipsis
        '\u00a0': ' ',                  # Non-breaking space
        '\u00ad': '-',                  # Soft hyphen
    }
    
    for search, replace in replacements.items():
        text = text.replace(search, replace)
        
    # Forcefully encode to ASCII, ignoring any remaining rogue characters, and decode back
    return text.encode('ascii', 'ignore').decode('ascii')


# ---------------------------------------------------------
# THE UNIVERSAL LLM PROMPT (Used for both Option A & B)
# ---------------------------------------------------------
UNIVERSAL_SYSTEM_PROMPT = """
You are a Universal Document & Media Intelligence Analyst. Analyze the following extracted text from an uploaded document, presentation, dataset, or video transcript.
Your task is to provide a comprehensive, detailed breakdown of the content. Adapt your tone and extraction to the content type (e.g., clinical trial, technical tutorial, business meeting, conference agenda, event brochure).

CRITICAL GUARDRAIL: You must ONLY use the information explicitly provided in the content. Do not hallucinate data.

Format requirements (Return ONLY valid JSON):
{
  "executive_summary": "A detailed 3-4 sentence paragraph summarizing the core theme and purpose of the content.",
  "core_topics": ["Topic 1", "Topic 2", "Topic 3"],
  "detailed_breakdown": [
    {"section": "Section Name", "details": "Detailed explanation of this section's content, arguments, or data."}
  ],
  "metrics_table": [
    {"metric_name": "Metric Name", "value": "Value"}
  ]
}

LENGTH GUIDANCE:
- For long videos/transcripts (10+ minutes) or large PDFs, generate 6 to 12 objects in the `detailed_breakdown` array to chronologically cover all major arguments, chapters, and tutorial steps in extreme detail. Do not skip important segments. 

METRICS TABLE GUIDANCE (ADAPT TO CONTENT TYPE):
- For Clinical/Scientific text: Extract Response Rates, Sample Sizes, p-values, adverse events, etc.
- For Datasets/Agendas (CSVs/Excel): Extract aggregate insights (e.g., "Total Records", "Number of High Signal Items", "Primary Therapeutic Area").
- For Event Brochures/Administrative Docs: Extract key logistical data (e.g., "Event Dates", "Hotel/Location", "Registration Fee", "Contact Number", "Bank Details").
- If no quantitative or structured data exists across any of these categories, return an empty list [] for the metrics_table.

Respond ONLY with valid JSON.
"""

def simulate_docuintel_extraction(abstract_id: str, title: str) -> str:
    print(f"\n[DocuIntel Triggered] HIGH priority detected for {abstract_id}")
    print(f"-> Automatically fetching presentation poster for: {title}")
    time.sleep(1.5) 
    print("-> Document fetched and text extracted successfully.")
    return f"Simulated extracted methodology, tabular data, and trial results from the PDF poster for {title}."

def rank_abstract(title: str, abstract: str, abstract_id: str = "UNKNOWN_ID") -> dict:
    context = retrieve_context(abstract, top_k=3)
    
    prompt = f'''
You are an oncology conference analyst.
Business Context: {context}
Conference Abstract Title: {title}
Abstract: {abstract}

Rank into: HIGH, MEDIUM, LOW, IRRELEVANT.
Return ONLY VALID JSON:
{{
 "rank":"",
 "confidence":"",
 "disease_area":"",
 "trial_phase":"",
 "drug_mentions":[],
 "biomarkers":[],
 "reasons":[]
}}
'''
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )
    
    result = _parse_json(response.choices[0].message.content)
    
    if result.get("rank") == "HIGH":
        pdf_text = simulate_docuintel_extraction(abstract_id, title)
        result["docuintel_status"] = "PDF Extracted. Ready for Tabular Analysis."
        result["raw_pdf_text"] = pdf_text
        
    return result

def generate_deep_summary(abstract_id: str, title: str, rank: str) -> dict:
    """Powers Option A (Pipeline Simulation). Uses the Universal Prompt."""
    record = MOCK_ARCHIVE.get(abstract_id)
    if not record:
        return {"status": "NOT_FOUND - manual upload required"}

    # Apply the sanitization firewall to prevent Unicode errors
    safe_title = _sanitize_text(title)
    safe_content = _sanitize_text(record['full_text'][:25000])

    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": UNIVERSAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Title: {safe_title}\nContent:\n{safe_content}"}
            ],
            temperature=0.1
        )
        
        summary = _parse_json(response.choices[0].message.content)
        return {"status": "FETCHED_AND_SUMMARISED", "data": summary}
    except Exception as e:
        return {"error": str(e)}

def _parse_json(text: str) -> dict:
    try:
        clean_text = re.sub(r'```json|```', '', text.strip()).strip()
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            clean_text = match.group(0)
        return json.loads(clean_text)
    except Exception as e:
        return {"error": f"Failed to parse LLM output: {str(e)}", "raw_output": text}

def analyze_uploaded_document(filename: str, content: str) -> dict:
    """Powers Option B (Live Uploads) and Option C (Link Paste). Uses the Universal Prompt."""
    
    # Apply the sanitization firewall to prevent Unicode errors from PDF/PPTX/Web extracts
    safe_filename = _sanitize_text(filename)
    safe_content = _sanitize_text(content[:25000])
    
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": UNIVERSAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Filename: {safe_filename}\nContent:\n{safe_content}"}
            ],
            temperature=0.1
        )
        summary = _parse_json(response.choices[0].message.content)
        return {"status": "SUCCESS", "data": summary}
    except Exception as e:
        return {"error": str(e)}

# ---------------------------------------------------------
# LIVE MEDIA TRANSCRIPTION (WHISPER AI)
# ---------------------------------------------------------
def transcribe_media(file_bytes: bytes, filename: str) -> str:
    """Uses Groq's Whisper API to extract audio/video and transcribe it into raw text."""
    if len(file_bytes) > 25 * 1024 * 1024:
        return "Error: Video file exceeds the 25MB limit for the Whisper Audio API. Please upload a shorter clip for this demo."
    
    try:
        transcription = client.audio.transcriptions.create(
          file=(filename, file_bytes),
          model="whisper-large-v3", 
          response_format="json",
        )
        return transcription.text
    except Exception as e:
        return f"Error transcribing media file: {str(e)}"