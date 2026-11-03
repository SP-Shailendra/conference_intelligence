import os
import io
from fastapi import FastAPI, Request, UploadFile, File
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List
import PyPDF2
from pptx import Presentation  
import docx  
import pandas as pd  

# IMPORTS FOR UNIVERSAL URL SCRAPING
import yt_dlp
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound

# Import your existing services
from services.pubmed_service import fetch_pubmed_abstracts
from services.llm_service import rank_abstract, generate_deep_summary, analyze_uploaded_document, transcribe_media
from services.synthetic_service import generate_synthetic_abstracts, generate_bulk_agenda
from services.roi_service import calculate_roi_metrics
from data.knowledge import MOCK_ARCHIVE  

app = FastAPI(title="Conference Intelligence API")

# Initialize the templates directory for the dashboard
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# ---------------------------------------------------------
# TEXT SANITIZER (The ASCII Firewall)
# ---------------------------------------------------------
def clean_text_for_llm(text: str) -> str:
    """
    Forces all text into safe ASCII characters to prevent Windows/Python locale crashes.
    """
    if not text:
        return ""
    
    # Replace fancy typography with safe keyboard equivalents
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
        
    # Nuke any remaining unencodable characters
    return text.encode('ascii', 'ignore').decode('ascii')


# ---------------------------------------------------------
# Pydantic Models (Data Validation)
# ---------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    max_results: int = 5

class RankRequest(BaseModel):
    abstract_id: str = "UNKNOWN_ID"
    title: str
    abstract: str

class DeepSummaryRequest(BaseModel):
    abstract_id: str
    title: str
    rank: str

class SyntheticRequest(BaseModel):
    topic: str
    count: int = 2

class UrlRequest(BaseModel):
    url: str

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@app.get("/")
def root_redirect():
    return RedirectResponse(url="/dashboard", status_code=307)

@app.get("/health")
def health_check():
    return {"status": "API is running successfully"}

@app.post("/api/fetch-abstracts")
def fetch_abstracts(request: SearchRequest):
    records = fetch_pubmed_abstracts(request.query, request.max_results)
    return {"count": len(records), "data": records}

@app.post("/api/rank-abstract")
def rank_single_abstract(request: RankRequest):
    result = rank_abstract(request.title, request.abstract, request.abstract_id)
    return {"title": request.title, "analysis": result}

@app.post("/api/deep-summary")
def get_deep_summary(request: DeepSummaryRequest):
    result = generate_deep_summary(request.abstract_id, request.title, request.rank)
    return {"abstract_id": request.abstract_id, "summary": result}

@app.post("/api/generate-synthetic")
def generate_synthetic(request: SyntheticRequest):
    data = generate_synthetic_abstracts(request.topic, request.count)
    return {"data": data}

@app.get("/api/export-bulk-agenda")
def export_bulk_agenda():
    df = generate_bulk_agenda(1000)
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    response = StreamingResponse(iter([stream.getvalue()]), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=dataset1_conference_agenda.csv"
    return response

@app.post("/api/analyze-upload")
async def analyze_upload(file: UploadFile = File(...)):
    """Receives a file, extracts text universally (PDF, PPTX, TXT, DOCX, XLSX, MP4, Audio, Links), and sends it to the LLM."""
    extracted_text = ""
    
    try:
        ext = file.filename.lower()
        file_bytes = await file.read() 
        
        # 1. Handle PDFs
        if ext.endswith('.pdf'):
            pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            for page in pdf_reader.pages:
                text = page.extract_text()
                if text:
                    extracted_text += text + "\n"
                    
        # 2. Handle PowerPoint Presentations
        elif ext.endswith(('.pptx', '.ppt')):
            presentation = Presentation(io.BytesIO(file_bytes))
            for slide in presentation.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        extracted_text += shape.text + "\n"
                        
        # 3. Handle Word Documents
        elif ext.endswith(('.docx', '.doc')):
            doc = docx.Document(io.BytesIO(file_bytes))
            extracted_text = "\n".join([para.text for para in doc.paragraphs])
            
        # 4. Handle Excel Spreadsheets
        elif ext.endswith(('.xlsx', '.xls', '.csv')):
            if ext.endswith('.csv'):
                df = pd.read_csv(io.BytesIO(file_bytes))
            else:
                df = pd.read_excel(io.BytesIO(file_bytes))
            extracted_text = df.head(100).to_string()
            
        # 5. Handle Live Direct Video/Audio Uploads using Whisper API
        elif ext.endswith(('.mp4', '.mov', '.avi', '.mp3', '.wav', '.m4a')):
            transcript = transcribe_media(file_bytes, file.filename)
            if transcript.startswith("Error"):
                return {"error": transcript}
                
            extracted_text = f"""
            [SYSTEM: LIVE WHISPER TRANSCRIPT EXTRACTED]
            Source File: {file.filename}
            Transcript: {transcript}
            """

        # 6. Handle Plain Text (Fallback)
        else:
            extracted_text = file_bytes.decode("utf-8", errors="ignore").strip()
            
        if not extracted_text.strip():
            return {"error": "Could not extract readable text. The document may consist entirely of scanned images without embedded text."}

        # --- THE FIREWALL ---
        # Clean the text to pure ASCII right before sending to Groq
        safe_extracted_text = clean_text_for_llm(extracted_text)
        safe_filename = clean_text_for_llm(file.filename)

        # Send the extracted text to our LLM function
        result = analyze_uploaded_document(safe_filename, safe_extracted_text)
        return result

    except Exception as e:
        return {"error": f"Failed to process file: {str(e)}"}

@app.post("/api/analyze-url")
async def analyze_url_endpoint(request: UrlRequest):
    """Receives a direct URL string, scrapes the media transcript/metadata universally, and sends it to the LLM."""
    url = request.url.strip()
    parsed_url = urlparse(url)
    extracted_text = ""
    
    try:
        # PATH A: YouTube Link (Get Deep Transcript)
        if "youtube.com" in parsed_url.netloc or "youtu.be" in parsed_url.netloc:
            video_id = None
            if "youtube.com" in parsed_url.netloc:
                query_params = parse_qs(parsed_url.query)
                if "v" in query_params:
                    video_id = query_params["v"][0]
            elif "youtu.be" in parsed_url.netloc:
                video_id = parsed_url.path.lstrip("/")

            if video_id:
                try:
                    try:
                        yt_instance = YouTubeTranscriptApi()
                        fetched_transcript = yt_instance.fetch(video_id)
                        if hasattr(fetched_transcript, 'to_raw_data'):
                            transcript_list = fetched_transcript.to_raw_data()
                            full_transcript = " ".join([t['text'] for t in transcript_list])
                        else:
                            full_transcript = " ".join([t.text for t in fetched_transcript])
                    except AttributeError:
                        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                        full_transcript = " ".join([t['text'] for t in transcript_list])
                        
                    extracted_text = f"Source URL: {url}\nTranscript: {full_transcript}"
                except TranscriptsDisabled:
                    return {"error": "Subtitles are disabled for this YouTube video."}
                except NoTranscriptFound:
                    return {"error": "No transcript was found for this YouTube video."}
                except Exception as e:
                    return {"error": f"Could not fetch YouTube transcript. Error: {str(e)}"}
            else:
                return {"error": "Invalid YouTube URL format."}
                
        # PATH B: Universal Link (yt-dlp for Vimeo, TED, etc.)
        else:
            ydl_opts = {'quiet': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown Video Title')
                desc = info.get('description', 'No description available.')
                uploader = info.get('uploader', 'Unknown Author')
                
                extracted_text = f"""
                [SYSTEM: UNIVERSAL MEDIA LINK DETECTED]
                Source URL: {url}
                Author/Uploader: {uploader}
                Video Title: {title}
                Video Description/Metadata: {desc}
                """
                
        if not extracted_text.strip():
            return {"error": "Could not extract readable text from the provided link."}

        # --- THE FIREWALL ---
        safe_extracted_text = clean_text_for_llm(extracted_text)
        safe_url = clean_text_for_llm(url)

        # Send the extracted text to our Universal LLM function
        result = analyze_uploaded_document(safe_url, safe_extracted_text)
        return result

    except Exception as e:
        return {"error": f"Failed to process link: {str(e)}. The site may be blocking scrapers or the link is invalid."}

# ---------------------------------------------------------
# UI Dashboard Routes
# ---------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
def render_dashboard(request: Request):
    metrics = calculate_roi_metrics()
    bulk_df = generate_bulk_agenda(1000)
    metrics.update({
        "total_abs": "1,000",
        "high_signal": str(int(bulk_df['Is_High_Signal'].sum())),
        "oral_count": str(int((bulk_df['Session_Type'] == 'Oral').sum())),
        "poster_count": str(int((bulk_df['Session_Type'] == 'Poster').sum()))
    })
    
    # We don't necessarily need mock_options on the dashboard anymore since the UI moved, 
    # but keeping it doesn't hurt and ensures backward compatibility if you revert anything.
    mock_options = []
    for m_id, m_data in MOCK_ARCHIVE.items():
        title = m_data.get("title", f"{m_id} - {m_data.get('content_type', 'Document')}")
        mock_options.append({"id": m_id, "title": title})
    
    context = {"request": request, "mock_options": mock_options}
    context.update(metrics)
    
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)

# ---> NEW ROUTE FOR THE WORKSPACE PAGE <---
@app.get("/workspace", response_class=HTMLResponse)
def render_workspace(request: Request):
    # Pass the mock archive options so Option A continues to work flawlessly in the new workspace
    mock_options = []
    for m_id, m_data in MOCK_ARCHIVE.items():
        title = m_data.get("title", f"{m_id} - {m_data.get('content_type', 'Document')}")
        mock_options.append({"id": m_id, "title": title})
    
    return templates.TemplateResponse(request=request, name="workspace.html", context={"mock_options": mock_options})