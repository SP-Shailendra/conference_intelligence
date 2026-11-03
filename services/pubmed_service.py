import requests
import xml.etree.ElementTree as ET

def fetch_pubmed_abstracts(search_term: str, max_results: int = 5):
    # 1. Search for PMIDs
    search_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        f"esearch.fcgi?db=pubmed&term={search_term}&retmax={max_results}&retmode=json"
    )
    search_response = requests.get(search_url)
    pmids = search_response.json().get("esearchresult", {}).get("idlist", [])
    
    if not pmids:
        return []

    # 2. Fetch Abstract details
    pmid_string = ",".join(pmids)
    fetch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        f"efetch.fcgi?db=pubmed&id={pmid_string}&retmode=xml"
    )
    xml_response = requests.get(fetch_url)
    root = ET.fromstring(xml_response.content)
    
    records = []
    for article in root.findall(".//PubmedArticle"):
        try:
            title = article.findtext(".//ArticleTitle")
            abstract_parts = article.findall(".//AbstractText")
            abstract = " ".join([a.text for a in abstract_parts if a.text])
            
            if abstract:
                records.append({
                    "id": article.findtext(".//PMID"),
                    "title": title,
                    "abstract": abstract
                })
        except Exception:
            continue
            
    return records