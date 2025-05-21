import requests
import json
import time
import os
import re
import tkinter as tk
from tkinter import filedialog

# --- Configuration ---
UNPAYWALL_EMAIL = 'jaustind1@gmail.com' # User's email
CROSSREF_API_URL = 'https://api.crossref.org/works'
UNPAYWALL_API_URL_BASE = 'https://api.unpaywall.org/v2/'
SEMANTIC_SCHOLAR_API_URL_BASE = 'https://api.semanticscholar.org/graph/v1/paper/' # Semantic Scholar API

REQUEST_TIMEOUT_API = 15  # seconds for API calls
REQUEST_TIMEOUT_DOWNLOAD = 60 # seconds for PDF downloads
USER_AGENT = 'ReferenceCheckerApp/1.3 (mailto:{})'.format(UNPAYWALL_EMAIL) # Version bump
DOWNLOAD_FOLDER = 'downloaded_papers'
# Semantic Scholar API Key (optional, but recommended for higher rate limits)
# SEMANTIC_SCHOLAR_API_KEY = None # Or 'YOUR_API_KEY'

# --- Helper Functions ---

def sanitize_filename(name):
    name = str(name) 
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    return name[:100]

def get_doi_from_crossref(reference_string):
    headers = {'User-Agent': USER_AGENT}
    params = {'query.bibliographic': reference_string, 'rows': 1}
    try:
        response = requests.get(CROSSREF_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_API)
        response.raise_for_status()
        data = response.json()
        if data['message']['items']:
            item = data['message']['items'][0]
            doi = item.get('DOI')
            title_list = item.get('title', [])
            title = title_list[0] if title_list else "No title found"
            return doi, title
        return None, None
    except requests.exceptions.RequestException as e:
        print(f"  [CrossRef Error] Could not query CrossRef for '{reference_string[:50]}...': {e}")
        return None, None
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  [CrossRef Error] Problem with CrossRef response for '{reference_string[:50]}...': {e}")
        return None, None

def get_open_access_info_unpaywall(doi): # Renamed for clarity
    if not doi: return None
    headers = {'User-Agent': USER_AGENT}
    url = f"{UNPAYWALL_API_URL_BASE}{doi}?email={UNPAYWALL_EMAIL}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_API)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  [Unpaywall Error] Could not query Unpaywall for DOI '{doi}': {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"  [Unpaywall Error] Could not decode JSON from Unpaywall for DOI '{doi}': {e}")
        return None

def get_pdf_info_from_semantic_scholar(doi):
    """
    Tries to find an open access PDF URL and title from Semantic Scholar.
    Returns (pdf_url, title) or (None, None).
    """
    if not doi: return None, None
    
    # Fields to retrieve from Semantic Scholar API
    fields = "isOpenAccess,openAccessPdf,title,externalIds"
    url = f"{SEMANTIC_SCHOLAR_API_URL_BASE}{doi}?fields={fields}"
    
    headers = {'User-Agent': USER_AGENT}
    # If you have an API key for Semantic Scholar, add it to headers:
    # if SEMANTIC_SCHOLAR_API_KEY:
    #     headers['x-api-key'] = SEMANTIC_SCHOLAR_API_KEY
        
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_API)
        response.raise_for_status()
        data = response.json()
        
        title = data.get('title', "No title found") # Get title
        
        if data.get('isOpenAccess') and data.get('openAccessPdf') and data['openAccessPdf'].get('url'):
            pdf_url = data['openAccessPdf']['url']
            return pdf_url, title
        # Even if isOpenAccess is true, sometimes openAccessPdf might be missing or null
        # print(f"  [Semantic Scholar] isOpenAccess: {data.get('isOpenAccess')}, PDF info: {data.get('openAccessPdf')}")
        return None, title # Return title even if no PDF URL, might be useful
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"  [Semantic Scholar] DOI '{doi}' not found.")
        elif e.response.status_code == 429: # Too Many Requests
            print(f"  [Semantic Scholar] Rate limit exceeded for DOI '{doi}'. Try again later or use an API key.")
        else:
            print(f"  [Semantic Scholar] HTTP error for DOI '{doi}': {e}")
        return None, None
    except requests.exceptions.RequestException as e:
        print(f"  [Semantic Scholar] Request error for DOI '{doi}': {e}")
        return None, None
    except json.JSONDecodeError:
        print(f"  [Semantic Scholar] Could not decode JSON response for DOI '{doi}'.")
        return None, None

def download_pdf(pdf_url, output_folder, doi, title, source_service="Unknown"):
    if not pdf_url:
        return None, "No PDF URL provided."

    abs_output_folder = os.path.abspath(output_folder)
    # print(f"    DEBUG: Absolute download folder target: {abs_output_folder}")
    if not os.path.exists(abs_output_folder):
        print(f"    DEBUG: Output folder {abs_output_folder} does not exist. This shouldn't happen if os.makedirs worked.")

    browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    local_headers = {'User-Agent': browser_user_agent}

    filepath = None 
    try:
        doi_filename_part = doi.replace('/', '_').replace('.', '-')
        if title and title not in ["No title found", "Unknown Title"]:
            title_words = str(title).split(' ') 
            short_title_part = '_'.join(title_words[0:min(len(title_words), 5)])
        else:
            short_title_part = "untitled"
        sanitized_title_short = sanitize_filename(short_title_part)
        
        filename = f"{doi_filename_part}__{sanitized_title_short}.pdf"
        filepath = os.path.join(abs_output_folder, filename)

        print(f"    Attempting to download PDF from {source_service}: {pdf_url}")
        # print(f"    Will try to save to: {filepath}")

        pdf_response = requests.get(pdf_url, stream=True, timeout=REQUEST_TIMEOUT_DOWNLOAD, headers=local_headers)
        
        if pdf_response.status_code == 403:
            print(f"    ❌ Server returned 403 Forbidden. Response text (first 200 chars): {pdf_response.text[:200]}")
            pdf_response.raise_for_status() 
        pdf_response.raise_for_status()

        content_type = pdf_response.headers.get('content-type', '').lower()
        if 'application/pdf' not in content_type:
            if not pdf_url.lower().endswith('.pdf') and '.pdf?' not in pdf_url.lower():
                 print(f"    ⚠️ Warning: Content-type is '{content_type}'. URL doesn't end with .pdf. Proceeding, but may not be a PDF.")
        
        file_written_successfully = False
        with open(filepath, 'wb') as f:
            for chunk in pdf_response.iter_content(chunk_size=8192):
                if chunk: 
                    f.write(chunk)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                file_written_successfully = True
            elif os.path.exists(filepath): 
                 print(f"    ⚠️ PDF created but is empty (0 bytes): {filepath}")
                 return None, f"PDF is empty (0 bytes) for {pdf_url}" 
            else: 
                print(f"    ❌ File not found after write attempt: {filepath}")
                return None, f"File not found after write attempt for {pdf_url}"

        if file_written_successfully:
            file_size = os.path.getsize(filepath)
            print(f"    ✅ PDF downloaded successfully via {source_service} as: {filepath} ({file_size} bytes)")
            return filepath, "Downloaded successfully."
        else:
            print(f"    ❌ PDF download (via {source_service}) reported success, but file integrity check failed for: {filepath}")
            return None, "Download succeeded but file check failed."
    except requests.exceptions.Timeout:
        print(f"    ❌ Download timed out (via {source_service}) for {pdf_url}.")
        return None, f"Download timed out for {pdf_url}."
    except requests.exceptions.HTTPError as e:
        print(f"    ❌ HTTP error (via {source_service}) during PDF download from {pdf_url}: {e}")
        return None, f"Failed to download PDF from {pdf_url}: {e}"
    except requests.exceptions.RequestException as e:
        print(f"    ❌ Request exception (via {source_service}) during PDF download from {pdf_url}: {e}")
        return None, f"Failed to download PDF from {pdf_url}: {e}"
    except IOError as e: 
        print(f"    ❌ File system error (via {source_service}) for {filepath}: {e}")
        return None, f"File system error for {filepath}: {e}"
    except Exception as e:
        print(f"    ❌ An unexpected error (via {source_service}) occurred during PDF download ({pdf_url}): {e}")
        return None, f"An unexpected error occurred during PDF download: {e}"

# --- Main Processing Logic ---
def process_references(reference_list):
    results = {
        'downloaded_pdf': [], 'open_access_no_pdf_link': [], 'paywalled': [],
        'doi_not_found': [], 'unpaywall_data_unavailable': [], 'error_processing': []
    }
    if not UNPAYWALL_EMAIL or UNPAYWALL_EMAIL == 'YOUR_EMAIL@example.com':
        print("🛑 ERROR: Please set your email address in the UNPAYWALL_EMAIL variable in the script.")
        return results

    # initial_cwd = os.getcwd() # Not strictly needed here if abs_download_folder is defined once
    abs_download_folder = os.path.abspath(DOWNLOAD_FOLDER)
    # print(f"DEBUG: CWD at start of process_references: {os.getcwd()}") # Optional debug
    # print(f"DEBUG: Attempting to create/verify download folder at: {abs_download_folder}") # Optional debug
    os.makedirs(abs_download_folder, exist_ok=True) 
    print(f"PDFs will be saved to '{abs_download_folder}/' folder.")
    print(f"\nProcessing {len(reference_list)} references...\n")

    for i, ref_string in enumerate(reference_list):
        print(f"Processing reference {i+1}/{len(reference_list)}: \"{ref_string[:70]}...\"")
        doi, crossref_title = get_doi_from_crossref(ref_string)

        if not doi:
            print(f"  DOI not found for: \"{ref_string[:70]}...\"")
            results['doi_not_found'].append({"original_reference": ref_string, "notes": "DOI could not be retrieved."})
            time.sleep(0.25) # Shorter sleep for quicker local errors
            continue

        article_title_for_processing = crossref_title if crossref_title and crossref_title != "No title found" else "Unknown Title"
        print(f"  Found DOI: {doi} (Title: {article_title_for_processing})")
        
        unpaywall_data = get_open_access_info_unpaywall(doi)
        time.sleep(0.25) # Sleep after Unpaywall API call

        publisher_landing_url = None
        final_title = article_title_for_processing # Default to CrossRef title

        if not unpaywall_data:
            print(f"  Could not retrieve data from Unpaywall for DOI: {doi}. Trying Semantic Scholar as fallback.")
            publisher_landing_url = f"https://doi.org/{doi}"
            
            # Try Semantic Scholar if Unpaywall fails completely
            ss_pdf_url, ss_title = get_pdf_info_from_semantic_scholar(doi)
            time.sleep(0.25) # Sleep after Semantic Scholar API call
            
            entry_data = {
                "original_reference": ref_string, "doi": doi, "title": ss_title or final_title,
                "publisher_landing_url": publisher_landing_url, "oa_status": "unknown (Unpaywall failed)"
            }

            if ss_pdf_url:
                print(f"  [Semantic Scholar] Found PDF for Unpaywall-failed item: {ss_pdf_url}")
                downloaded_filepath, download_status = download_pdf(ss_pdf_url, abs_download_folder, doi, ss_title or final_title, source_service="Semantic Scholar")
                entry_data.update({'pdf_url': ss_pdf_url, 'download_status': download_status, 'oa_source': 'Semantic Scholar'})
                if downloaded_filepath:
                    entry_data['local_pdf_path'] = downloaded_filepath
                    results['downloaded_pdf'].append(entry_data)
                else:
                    results['open_access_no_pdf_link'].append(entry_data)
            else:
                entry_data["notes"] = "Unpaywall API failed; Semantic Scholar found no PDF."
                results['unpaywall_data_unavailable'].append(entry_data) # Keep it in this category
            continue # Move to next reference
        
        # --- Process Unpaywall Data ---
        final_title = unpaywall_data.get('title') or article_title_for_processing
        publisher_landing_url = unpaywall_data.get('doi_url')

        entry = {
            "original_reference": ref_string, "doi": doi, "title": final_title,
            "journal": unpaywall_data.get('journal_name', 'N/A'),
            "year": unpaywall_data.get('published_date', 'N/A')[:4] if unpaywall_data.get('published_date') else 'N/A',
            "oa_status": unpaywall_data.get('oa_status', 'unknown'),
            "publisher_landing_url": publisher_landing_url or f"https://doi.org/{doi}",
            "oa_source": "Unpaywall" # Default source
        }
        
        pdf_download_path_from_unpaywall = None
        unpaywall_pdf_url = None

        if unpaywall_data.get('is_oa'):
            best_oa_location = unpaywall_data.get('best_oa_location', {})
            unpaywall_pdf_url = best_oa_location.get('url_for_pdf') if best_oa_location else None
            oa_content_landing_url = best_oa_location.get('url') if best_oa_location else None
            entry['oa_content_landing_url'] = oa_content_landing_url if oa_content_landing_url != unpaywall_pdf_url else None

            if unpaywall_pdf_url:
                entry['pdf_url'] = unpaywall_pdf_url # Log Unpaywall's found PDF URL
                temp_dl_path, temp_dl_status = download_pdf(unpaywall_pdf_url, abs_download_folder, doi, final_title, source_service="Unpaywall")
                entry['download_status'] = temp_dl_status # Log attempt status
                if temp_dl_path:
                    pdf_download_path_from_unpaywall = temp_dl_path
            
            if pdf_download_path_from_unpaywall:
                entry['local_pdf_path'] = pdf_download_path_from_unpaywall
                results['downloaded_pdf'].append(entry)
            else:
                # Unpaywall said OA, but no PDF URL or download failed. Try Semantic Scholar.
                if unpaywall_pdf_url: # If there was a URL but it failed
                    print(f"  Unpaywall PDF download failed for {doi}. Trying Semantic Scholar...")
                else: # Unpaywall said OA but gave no direct PDF link
                    print(f"  Unpaywall found OA but no direct PDF link for {doi}. Trying Semantic Scholar...")
                
                ss_pdf_url, ss_title = get_pdf_info_from_semantic_scholar(doi)
                time.sleep(0.25) # Sleep after Semantic Scholar API call

                if ss_pdf_url:
                    print(f"  [Semantic Scholar] Found alternative PDF: {ss_pdf_url}")
                    # Use the title from Semantic Scholar if it's better or available
                    title_for_ss_download = ss_title if (ss_title and ss_title != "No title found") else final_title
                    
                    downloaded_filepath, download_status = download_pdf(ss_pdf_url, abs_download_folder, doi, title_for_ss_download, source_service="Semantic Scholar")
                    entry['pdf_url'] = ss_pdf_url # Update with the URL that was used
                    entry['download_status'] = download_status
                    entry['oa_source'] = "Semantic Scholar"
                    if downloaded_filepath:
                        entry['local_pdf_path'] = downloaded_filepath
                        results['downloaded_pdf'].append(entry)
                    else:
                        entry['notes'] = entry.get('notes', '') + " Semantic Scholar PDF download also failed."
                        results['open_access_no_pdf_link'].append(entry)
                else: # Semantic scholar found no PDF either
                    print(f"  [Semantic Scholar] No PDF link found as backup for {doi}.")
                    entry['notes'] = entry.get('notes', '') + (" Unpaywall provided no PDF link." if not unpaywall_pdf_url else " Unpaywall PDF download failed.") + " Semantic Scholar also found no PDF link."
                    results['open_access_no_pdf_link'].append(entry)
        else: 
            entry['notes'] = f"Unpaywall indicated not OA (is_oa: False, status: {entry['oa_status']})."
            results['paywalled'].append(entry)
            print(f"  💰 Paywalled or not OA (is_oa: False, status: {entry['oa_status']}) according to Unpaywall.")
            # Optionally, you could try Semantic Scholar here too if you want to be aggressive
            # print(f"  Attempting Semantic Scholar for paywalled item {doi} as a long shot...")
            # ss_pdf_url, ss_title = get_pdf_info_from_semantic_scholar(doi)
            # time.sleep(0.25)
            # if ss_pdf_url: ... (handle download attempt) ...
            
    print("\n--- Processing Complete ---")
    return results

def print_results(results):
    print("\n--- Results Summary ---")
    if results['downloaded_pdf']:
        print(f"\n✅ Downloaded Open Access PDFs ({len(results['downloaded_pdf'])}):")
        for item in results['downloaded_pdf']:
            print(f"  - Title: {item['title'][:60]}... (DOI: {item['doi']})")
            print(f"    Saved to: {item['local_pdf_path']}")
            print(f"    OA Status: {item.get('oa_status', 'N/A')}, Source: {item.get('oa_source', 'N/A')}, PDF URL: {item.get('pdf_url', 'N/A')}")
            if item.get('oa_content_landing_url'):
                print(f"    OA Content Page: {item['oa_content_landing_url']}")
            elif item.get('publisher_landing_url') != item.get('pdf_url'):
                 print(f"    Publisher Page: {item.get('publisher_landing_url', 'N/A')}")

    if results['open_access_no_pdf_link']:
        print(f"\n🔑 Open Access (PDF not downloaded/no direct link) ({len(results['open_access_no_pdf_link'])}):")
        for item in results['open_access_no_pdf_link']:
            print(f"  - Title: {item['title'][:60]}... (DOI: {item['doi']})")
            print(f"    OA Status: {item.get('oa_status', 'N/A')}. Source: {item.get('oa_source', 'Unpaywall/Unknown')}")
            print(f"    Notes: {item.get('notes', '')} {item.get('download_status', '')}")
            if item.get('pdf_url'): 
                print(f"    Attempted PDF URL: {item['pdf_url']}")
            if item.get('oa_content_landing_url'):
                print(f"    OA Content Page: {item['oa_content_landing_url']}")
            print(f"    Publisher Page: {item.get('publisher_landing_url', f'https://doi.org/{item.get("doi")}')}")

    if results['paywalled']:
        print(f"\n💰 Paywalled or Not OA according to Unpaywall ({len(results['paywalled'])}):")
        for item in results['paywalled']:
            print(f"  - Title: {item['title'][:60]}... (DOI: {item['doi']})")
            print(f"    Publisher Page: {item.get('publisher_landing_url', f'https://doi.org/{item.get("doi")}')}")
            print(f"    Notes: {item.get('notes', '')}")

    if results['doi_not_found']:
        print(f"\n❌ Failed (DOI not found) ({len(results['doi_not_found'])}):")
        for item in results['doi_not_found']:
            print(f"  - Reference: {item['original_reference'][:70]}...")

    if results['unpaywall_data_unavailable']: # This category now also implies Semantic Scholar didn't find a PDF if Unpaywall failed
        print(f"\n⚠️ Failed (Unpaywall data unavailable, and Semantic Scholar backup found no PDF) ({len(results['unpaywall_data_unavailable'])}):")
        for item in results['unpaywall_data_unavailable']:
            print(f"  - Title: {item['title'][:60]}... (DOI: {item['doi']})")
            print(f"    Check at: {item.get('publisher_landing_url', f'https://doi.org/{item.get("doi")}')}")
            
    if results['error_processing']:
        print(f"\n❓ Other Errors During Processing ({len(results['error_processing'])}):")
        for item in results['error_processing']:
            print(f"  - Title: {item.get('title', 'N/A')[:60]}... (DOI: {item.get('doi', 'N/A')}), Notes: {item.get('notes')}")
            if item.get('doi'):
                print(f"    Check at: {item.get('publisher_landing_url', f'https://doi.org/{item.get("doi")}')}")

# --- Main Execution ---
if __name__ == "__main__":
    # initial_cwd = os.getcwd() # Optional debug
    # print(f"DEBUG: Initial CWD at script start: {initial_cwd}") # Optional debug

    root = tk.Tk()
    root.withdraw() 

    input_filename = filedialog.askopenfilename(
        title="Select the .txt file with references",
        filetypes=(("Text files", "*.txt"), ("All files", "*.*")),
        initialdir=os.getcwd() # Start in current CWD
    )
    
    # print(f"DEBUG: CWD after filedialog: {os.getcwd()}") # Optional debug

    if not input_filename: 
        print("No file selected. Exiting.")
        exit()

    references_from_file = []
    try:
        with open(input_filename, 'r', encoding='utf-8') as f:
            references_from_file = [line.strip() for line in f if line.strip()]
        if not references_from_file:
            print(f"No references found in '{input_filename}' or the file is empty.")
            exit()
    except FileNotFoundError: 
        print(f"🚨 Error: File '{input_filename}' not found.")
        exit()
    except Exception as e:
        print(f"🚨 An error occurred while reading the file '{input_filename}': {e}")
        exit()

    results = process_references(references_from_file)
    print_results(results)