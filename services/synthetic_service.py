import json
import re
import random          # <-- MISSING IMPORT ADDED
import pandas as pd    # <-- MISSING IMPORT ADDED
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL

# Safeguard if the client fails to initialize
try:
    client = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    client = None

def generate_synthetic_abstracts(topic: str, count: int = 3) -> list:
    if not GROQ_API_KEY or client is None:
        return [{"error": "Groq API key is missing or client failed to initialize."}]

    prompt = f"""
    You are an expert clinical data generator. Generate {count} highly realistic synthetic 
    medical conference abstracts about {topic}.
    
    Return ONLY valid JSON in this exact structure, no intro or outro text:
    [
      {{
        "id": "SYNTH-100",
        "title": "Phase II study of...",
        "abstract": "Background: ... Methods: ... Results: ... Conclusion: ..."
      }}
    ]
    """
    
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7 # Higher temperature for creative data generation
        )
        
        text = response.choices[0].message.content
        clean_text = re.sub(r'```json|```', '', text.strip()).strip()
        return json.loads(clean_text)
    except Exception as e:
        return [{"error": f"Generation failed: {str(e)}"}]
    

def generate_bulk_agenda(n_abstracts=1000):
    """From Notebook Section 14: Generates a large-scale mock conference."""
    SESSION_TYPES = ['Oral', 'Poster', 'Other']
    SESSION_WEIGHTS = [0.20, 0.65, 0.15]
    THERAPEUTIC_AREAS = ['Oncology','Immunology','Cardiology','Neurology','Rare Disease','Metabolic']
    TRIAL_PHASES = ['Phase I','Phase II','Phase III','Phase IV','Preclinical']

    HIGH_TITLES = ['PD-L1 expression and response to pembrolizumab in advanced NSCLC', 'Nivolumab plus chemotherapy in first-line squamous NSCLC: Phase III results']
    LOW_TITLES = ['Sodium-glucose cotransporter-2 inhibitors in heart failure', 'Wearable ECG monitors for atrial fibrillation detection']

    records = []
    for i in range(n_abstracts):
        high = random.random() < 0.30
        records.append({
            'Abstract_ID': f'CONF-2025-{i+1:04d}',
            'Title': random.choice(HIGH_TITLES) if high else random.choice(LOW_TITLES),
            'Session_Type': random.choices(SESSION_TYPES, weights=SESSION_WEIGHTS, k=1)[0],
            'Therapeutic_Area': 'Oncology' if high else random.choice(THERAPEUTIC_AREAS),
            'Trial_Phase': random.choice(['Phase II','Phase III']) if high else random.choice(TRIAL_PHASES),
            'Is_High_Signal': high
        })
    
    return pd.DataFrame(records)