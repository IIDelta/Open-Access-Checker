import requests
import json
import time
import os
import re
import tkinter as tk
from tkinter import filedialog, scrolledtext, messagebox, ttk # Added ttk
import threading
import queue # For thread-safe GUI updates

# --- Configuration (Kept for backend, email is important) ---
UNPAYWALL_EMAIL = 'jaustind1@gmail.com' # User's email
CROSSREF_API_URL = 'https://api.crossref.org/works' #
UNPAYWALL_API_URL_BASE = 'https://api.unpaywall.org/v2/' #
SEMANTIC_SCHOLAR_API_URL_BASE = 'https://api.semanticscholar.org/graph/v1/paper/' #

REQUEST_TIMEOUT_API = 15 #
REQUEST_TIMEOUT_DOWNLOAD = 60 #
USER_AGENT = 'ReferenceCheckerApp/1.7_GUICopySummary (mailto:{})'.format(UNPAYWALL_EMAIL) # Version bump

# --- Backend Helper Functions (sanitize_filename, get_doi_from_crossref, etc. remain largely the same) ---
# ... (All helper functions: sanitize_filename, get_doi_from_crossref, 
#      get_open_access_info_unpaywall, get_pdf_info_from_semantic_scholar, 
#      download_pdf remain the same as in your provided script with live summary updates) ...
# For brevity, I'll assume these functions are identical to the previous version
# where they take log_callback and pass it down.

def sanitize_filename(name): #
    name = str(name) 
    name = re.sub(r'[<>:"/\\|?*]', '', name) #
    name = re.sub(r'\s+', '_', name) #
    return name[:100] #

def get_doi_from_crossref(reference_string, log_callback): #
    headers = {'User-Agent': USER_AGENT} #
    params = {'query.bibliographic': reference_string, 'rows': 1} #
    try:
        response = requests.get(CROSSREF_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT_API) #
        response.raise_for_status() #
        data = response.json() #
        if data['message']['items']: #
            item = data['message']['items'][0] #
            doi = item.get('DOI') #
            title_list = item.get('title', []) #
            title = title_list[0] if title_list else "No title found" #
            return doi, title #
        return None, None #
    except requests.exceptions.RequestException as e:
        log_callback(f"  [CrossRef Error] Could not query CrossRef for '{reference_string[:50]}...': {e}") #
        return None, None #
    except (json.JSONDecodeError, KeyError) as e:
        log_callback(f"  [CrossRef Error] Problem with CrossRef response for '{reference_string[:50]}...': {e}") #
        return None, None #

def get_open_access_info_unpaywall(doi, log_callback): #
    if not doi: return None #
    headers = {'User-Agent': USER_AGENT} #
    url = f"{UNPAYWALL_API_URL_BASE}{doi}?email={UNPAYWALL_EMAIL}" #
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_API) #
        response.raise_for_status() #
        return response.json() #
    except requests.exceptions.RequestException as e:
        log_callback(f"  [Unpaywall Error] Could not query Unpaywall for DOI '{doi}': {e}") #
        return None #
    except json.JSONDecodeError as e:
        log_callback(f"  [Unpaywall Error] Could not decode JSON from Unpaywall for DOI '{doi}': {e}") #
        return None #

def get_pdf_info_from_semantic_scholar(doi, log_callback): #
    if not doi: return None, None #
    fields = "isOpenAccess,openAccessPdf,title,externalIds" #
    url = f"{SEMANTIC_SCHOLAR_API_URL_BASE}{doi}?fields={fields}" #
    headers = {'User-Agent': USER_AGENT} #
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_API) #
        response.raise_for_status() #
        data = response.json() #
        title = data.get('title', "No title found") #
        if data.get('isOpenAccess') and data.get('openAccessPdf') and data['openAccessPdf'].get('url'): #
            pdf_url = data['openAccessPdf']['url'] #
            return pdf_url, title #
        return None, title #
    except requests.exceptions.HTTPError as e: #
        if e.response.status_code == 404: #
            log_callback(f"  [Semantic Scholar] DOI '{doi}' not found.") #
        elif e.response.status_code == 429: #
            log_callback(f"  [Semantic Scholar] Rate limit exceeded for DOI '{doi}'. Try again later or use an API key.") #
        else:
            log_callback(f"  [Semantic Scholar] HTTP error for DOI '{doi}': {e}") #
        return None, None #
    except requests.exceptions.RequestException as e: #
        log_callback(f"  [Semantic Scholar] Request error for DOI '{doi}': {e}") #
        return None, None #
    except json.JSONDecodeError: #
        log_callback(f"  [Semantic Scholar] Could not decode JSON response for DOI '{doi}'.") #
        return None, None #

def download_pdf(pdf_url, chosen_output_folder, doi, title, source_service="Unknown", log_callback=print): #
    if not pdf_url: #
        return None, "No PDF URL provided." #
    if not os.path.exists(chosen_output_folder): #
        log_callback(f"    ERROR: Output folder {chosen_output_folder} does not exist. Please select a valid folder.") #
        return None, f"Output folder {chosen_output_folder} does not exist." #

    browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' #
    local_headers = {'User-Agent': browser_user_agent} #
    filepath = None #
    try:
        doi_filename_part = doi.replace('/', '_').replace('.', '-') #
        if title and title not in ["No title found", "Unknown Title"]: #
            title_words = str(title).split(' ') #
            short_title_part = '_'.join(title_words[0:min(len(title_words), 5)]) #
        else:
            short_title_part = "untitled" #
        sanitized_title_short = sanitize_filename(short_title_part) #
        filename = f"{doi_filename_part}__{sanitized_title_short}.pdf" #
        filepath = os.path.join(chosen_output_folder, filename) #

        log_callback(f"    Attempting to download PDF from {source_service}: {pdf_url}") #
        pdf_response = requests.get(pdf_url, stream=True, timeout=REQUEST_TIMEOUT_DOWNLOAD, headers=local_headers) #
        if pdf_response.status_code == 403: #
            log_callback(f"    ❌ Server returned 403 Forbidden. Response text (first 200 chars): {pdf_response.text[:200]}") #
            pdf_response.raise_for_status() #
        pdf_response.raise_for_status() #

        content_type = pdf_response.headers.get('content-type', '').lower() #
        if 'application/pdf' not in content_type: #
            if not pdf_url.lower().endswith('.pdf') and '.pdf?' not in pdf_url.lower(): #
                 log_callback(f"    ⚠️ Warning: Content-type is '{content_type}'. URL doesn't end with .pdf. Proceeding, but may not be a PDF.") #
        
        file_written_successfully = False #
        with open(filepath, 'wb') as f: #
            for chunk in pdf_response.iter_content(chunk_size=8192): #
                if chunk: #
                    f.write(chunk) #
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0: #
                file_written_successfully = True #
            elif os.path.exists(filepath): #
                 log_callback(f"    ⚠️ PDF created but is empty (0 bytes): {filepath}") #
                 return None, f"PDF is empty (0 bytes) for {pdf_url}" #
            else: #
                log_callback(f"    ❌ File not found after write attempt: {filepath}") #
                return None, f"File not found after write attempt for {pdf_url}" #

        if file_written_successfully: #
            file_size = os.path.getsize(filepath) #
            log_callback(f"    ✅ PDF downloaded successfully via {source_service} as: {filepath} ({file_size} bytes)") #
            return filepath, "Downloaded successfully." #
        else: #
            log_callback(f"    ❌ PDF download (via {source_service}) reported success, but file integrity check failed for: {filepath}") #
            return None, "Download succeeded but file check failed." #
    except requests.exceptions.Timeout: #
        log_callback(f"    ❌ Download timed out (via {source_service}) for {pdf_url}.") #
        return None, f"Download timed out for {pdf_url}." #
    except requests.exceptions.HTTPError as e: #
        log_callback(f"    ❌ HTTP error (via {source_service}) during PDF download from {pdf_url}: {e}") #
        return None, f"Failed to download PDF from {pdf_url}: {e}" #
    except requests.exceptions.RequestException as e: #
        log_callback(f"    ❌ Request exception (via {source_service}) during PDF download from {pdf_url}: {e}") #
        return None, f"Failed to download PDF from {pdf_url}: {e}" #
    except IOError as e: #
        log_callback(f"    ❌ File system error (via {source_service}) for {filepath if filepath else 'unknown path'}: {e}") #
        return None, f"File system error for {filepath if filepath else 'unknown path'}: {e}" #
    except Exception as e: #
        log_callback(f"    ❌ An unexpected error (via {source_service}) occurred during PDF download ({pdf_url}): {e}") #
        return None, f"An unexpected error occurred during PDF download: {e}" #

# --- Main Backend Processing Logic ---
def process_references_backend(reference_list, chosen_download_folder, gui_update_callback): #
    if not UNPAYWALL_EMAIL or UNPAYWALL_EMAIL == 'YOUR_EMAIL@example.com': #
        gui_update_callback({'type': 'log', 'message': "🛑 ERROR: Please set your email address in the UNPAYWALL_EMAIL variable (top of the script)."}) #
        return #

    try:
        os.makedirs(chosen_download_folder, exist_ok=True) #
    except OSError as e: #
        gui_update_callback({'type': 'log', 'message': f"🛑 ERROR: Could not create download folder '{chosen_download_folder}': {e}"}) #
        return #

    gui_update_callback({'type': 'log', 'message': f"PDFs will be saved to '{chosen_download_folder}/' folder."}) #
    gui_update_callback({'type': 'log', 'message': f"\nProcessing {len(reference_list)} references...\n"}) #

    for i, ref_string in enumerate(reference_list): #
        gui_update_callback({'type': 'log', 'message': f"Processing reference {i+1}/{len(reference_list)}: \"{ref_string[:70]}...\""}) #
        doi, crossref_title = get_doi_from_crossref(ref_string, lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #

        base_entry_info = {"original_reference": ref_string, "doi": doi} #

        if not doi: #
            gui_update_callback({'type': 'log', 'message': f"  DOI not found for: \"{ref_string[:70]}...\""}) #
            summary_item = {**base_entry_info, "title": ref_string[:60] + "...", "status_info": "DOI not found", "url_info": "N/A"} #
            gui_update_callback({'type': 'summary_add', 'category_key': 'doi_not_found', 'item_data': summary_item}) #
            time.sleep(0.25) #
            continue #

        article_title_for_processing = crossref_title if crossref_title and crossref_title != "No title found" else "Unknown Title" #
        gui_update_callback({'type': 'log', 'message': f"  Found DOI: {doi} (Title: {article_title_for_processing})"}) #
        
        base_entry_info["title"] = article_title_for_processing #

        unpaywall_data = get_open_access_info_unpaywall(doi, lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
        time.sleep(0.25) #

        publisher_landing_url = f"https://doi.org/{doi}" #
        final_title = article_title_for_processing #
        entry_for_summary = {} #

        if not unpaywall_data: #
            gui_update_callback({'type': 'log', 'message': f"  Could not retrieve data from Unpaywall for DOI: {doi}. Trying Semantic Scholar as fallback."}) #
            ss_pdf_url, ss_title = get_pdf_info_from_semantic_scholar(doi, lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
            time.sleep(0.25) #
            
            final_title = ss_title or article_title_for_processing #
            entry_for_summary = { #
                **base_entry_info, "title": final_title, #
                "status_info": "Unpaywall failed. Semantic Scholar: " + ("PDF found" if ss_pdf_url else "No PDF"), #
                "url_info": ss_pdf_url or publisher_landing_url #
            }
            category_key_to_use = 'unpaywall_data_unavailable' #

            if ss_pdf_url: #
                gui_update_callback({'type': 'log', 'message': f"  [Semantic Scholar] Found PDF for Unpaywall-failed item: {ss_pdf_url}"}) #
                downloaded_filepath, download_status = download_pdf(ss_pdf_url, chosen_download_folder, doi, final_title, source_service="Semantic Scholar", log_callback=lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
                if downloaded_filepath: #
                    entry_for_summary["status_info"] = f"Downloaded via Semantic Scholar: {os.path.basename(downloaded_filepath)}" #
                    entry_for_summary["url_info"] = ss_pdf_url #
                    category_key_to_use = 'downloaded_pdf' #
                else: #
                    entry_for_summary["status_info"] = f"Semantic Scholar PDF found but download failed: {download_status}" #
                    category_key_to_use = 'open_access_no_pdf_link' #
            gui_update_callback({'type': 'summary_add', 'category_key': category_key_to_use, 'item_data': entry_for_summary}) #
            continue #
        
        final_title = unpaywall_data.get('title') or article_title_for_processing #
        publisher_landing_url = unpaywall_data.get('doi_url') or f"https://doi.org/{doi}" #
        
        entry_for_summary = { #
            **base_entry_info, "title": final_title, #
            "status_info": f"Unpaywall OA Status: {unpaywall_data.get('oa_status', 'unknown')}", #
            "url_info": publisher_landing_url #
        }
        category_key_to_use = 'paywalled' #

        pdf_download_path_from_unpaywall = None #
        unpaywall_pdf_url = None #

        if unpaywall_data.get('is_oa'): #
            best_oa_location = unpaywall_data.get('best_oa_location', {}) #
            unpaywall_pdf_url = best_oa_location.get('url_for_pdf') if best_oa_location else None #
            oa_content_landing_url = best_oa_location.get('url') if best_oa_location else None #
            
            entry_for_summary["url_info"] = oa_content_landing_url or publisher_landing_url #

            if unpaywall_pdf_url: #
                entry_for_summary["url_info"] = unpaywall_pdf_url #
                temp_dl_path, temp_dl_status = download_pdf(unpaywall_pdf_url, chosen_download_folder, doi, final_title, source_service="Unpaywall", log_callback=lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
                if temp_dl_path: #
                    pdf_download_path_from_unpaywall = temp_dl_path #
                    entry_for_summary["status_info"] = f"Downloaded via Unpaywall: {os.path.basename(pdf_download_path_from_unpaywall)}" #
                    category_key_to_use = 'downloaded_pdf' #
                else: #
                    entry_for_summary["status_info"] = f"Unpaywall PDF download failed: {temp_dl_status}" #
                    category_key_to_use = 'open_access_no_pdf_link' #
            else: #
                entry_for_summary["status_info"] = f"Unpaywall OA (Status: {entry_for_summary['status_info']}), no direct PDF." #
                category_key_to_use = 'open_access_no_pdf_link' #

            if not pdf_download_path_from_unpaywall: #
                gui_update_callback({'type': 'log', 'message': f"  Attempting Semantic Scholar backup for {doi}..."}) #
                ss_pdf_url, ss_title = get_pdf_info_from_semantic_scholar(doi, lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
                time.sleep(0.25) #
                if ss_pdf_url: #
                    gui_update_callback({'type': 'log', 'message': f"  [Semantic Scholar] Found alternative PDF: {ss_pdf_url}"}) #
                    title_for_ss_download = ss_title if (ss_title and ss_title != "No title found") else final_title #
                    downloaded_filepath, download_status = download_pdf(ss_pdf_url, chosen_download_folder, doi, title_for_ss_download, source_service="Semantic Scholar", log_callback=lambda msg: gui_update_callback({'type': 'log', 'message': msg})) #
                    entry_for_summary["url_info"] = ss_pdf_url #
                    if downloaded_filepath: #
                        entry_for_summary["status_info"] = f"Downloaded via Semantic Scholar: {os.path.basename(downloaded_filepath)}" #
                        category_key_to_use = 'downloaded_pdf' #
                    else: #
                        entry_for_summary["status_info"] = f"Unpaywall attempt failed. Semantic Scholar PDF found but download failed: {download_status}" #
                        # category_key_to_use remains 'open_access_no_pdf_link'
                else: #
                    gui_update_callback({'type': 'log', 'message': f"  [Semantic Scholar] No PDF link found as backup for {doi}."}) #
                    entry_for_summary["status_info"] += " Semantic Scholar found no PDF." #
        else: #
            entry_for_summary["status_info"] = f"Paywalled (Unpaywall: {unpaywall_data.get('oa_status', 'unknown')})" #
            category_key_to_use = 'paywalled' #
        
        gui_update_callback({'type': 'summary_add', 'category_key': category_key_to_use, 'item_data': entry_for_summary}) #
            
    gui_update_callback({'type': 'log', 'message': "\n--- Processing Complete ---"}) #

# --- GUI Application ---
class App: #
    def __init__(self, root_window): #
        self.root = root_window #
        self.root.title("Open Access Reference Checker") #

        self.input_file_path = tk.StringVar() #
        self.output_folder_path = tk.StringVar() #
        self.processing_thread = None #
        self.gui_update_queue = queue.Queue() #

        self.paned_window = tk.PanedWindow(self.root, orient=tk.VERTICAL, sashrelief=tk.RAISED) #
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) #

        controls_frame = tk.Frame(self.root) #
        controls_frame.pack(fill=tk.X, padx=10, pady=(10,0)) #
        
        tk.Button(controls_frame, text="Select Input File (.txt)", command=self.select_input_file).pack(side=tk.LEFT, padx=5, pady=5) #
        self.input_file_label = tk.Label(controls_frame, textvariable=self.input_file_path, relief=tk.GROOVE, width=40, anchor='w', justify=tk.LEFT) #
        self.input_file_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5) #

        tk.Button(controls_frame, text="Select Output Folder", command=self.select_output_folder).pack(side=tk.LEFT, padx=5, pady=5) #
        self.output_folder_label = tk.Label(controls_frame, textvariable=self.output_folder_path, relief=tk.GROOVE, width=40, anchor='w', justify=tk.LEFT) #
        self.output_folder_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5) #
        
        self.start_button = tk.Button(controls_frame, text="Start Processing", command=self.start_processing_thread, font=("Arial", 12, "bold"), bg="lightblue") #
        self.start_button.pack(side=tk.LEFT, pady=5, padx=10, ipady=5) #

        summary_frame = tk.Frame(self.paned_window, relief=tk.GROOVE, borderwidth=2) #
        self.paned_window.add(summary_frame, height=250) #

        summary_label = tk.Label(summary_frame, text="Live Summary:", font=("Arial", 10, "bold")) #
        summary_label.pack(pady=(5,0), anchor='w', padx=5) #
        
        self.summary_tree = ttk.Treeview(summary_frame, columns=("DOI", "StatusInfo", "URL"), show="headings") #
        self.summary_tree.heading("DOI", text="DOI") #
        self.summary_tree.heading("StatusInfo", text="Status / File / Note") #
        self.summary_tree.heading("URL", text="Relevant URL") #
        
        self.summary_tree.column("DOI", width=150, anchor='w') #
        self.summary_tree.column("StatusInfo", width=350, anchor='w') #
        self.summary_tree.column("URL", width=250, anchor='w') #

        summary_vsb = ttk.Scrollbar(summary_frame, orient="vertical", command=self.summary_tree.yview) #
        summary_hsb = ttk.Scrollbar(summary_frame, orient="horizontal", command=self.summary_tree.xview) #
        self.summary_tree.configure(yscrollcommand=summary_vsb.set, xscrollcommand=summary_hsb.set) #
        
        summary_vsb.pack(side=tk.RIGHT, fill=tk.Y) #
        summary_hsb.pack(side=tk.BOTTOM, fill=tk.X) #
        self.summary_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5) #

        self.tree_categories = { #
            'downloaded_pdf': self.summary_tree.insert("", tk.END, text="✅ Downloaded PDFs", open=True), #
            'open_access_no_pdf_link': self.summary_tree.insert("", tk.END, text="🔑 OA (No PDF/Download Failed)", open=True), #
            'paywalled': self.summary_tree.insert("", tk.END, text="💰 Paywalled (Unpaywall)", open=True), #
            'unpaywall_data_unavailable': self.summary_tree.insert("", tk.END, text="⚠️ Unpaywall/SS Data Failed", open=True), #
            'doi_not_found': self.summary_tree.insert("", tk.END, text="❌ DOI Not Found", open=True) #
        }
        self.summary_tree.config(show="tree headings") #

        log_frame = tk.Frame(self.paned_window, relief=tk.GROOVE, borderwidth=2) #
        self.paned_window.add(log_frame, height=200) #

        log_label = tk.Label(log_frame, text="Detailed Log:", font=("Arial", 10, "bold")) #
        log_label.pack(pady=(5,0), anchor='w', padx=5) #
        self.log_text_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=10) #
        self.log_text_area.pack(pady=5, padx=5, fill=tk.BOTH, expand=True) #
        self.log_text_area.configure(state='disabled') #

        self.check_gui_queue() #

    def select_input_file(self): #
        path = filedialog.askopenfilename( #
            title="Select the .txt file with references", #
            filetypes=(("Text files", "*.txt"), ("All files", "*.*")), #
            initialdir=os.getcwd() #
        )
        if path: #
            self.input_file_path.set(os.path.normpath(path)) #

    def select_output_folder(self): #
        path = filedialog.askdirectory( #
            title="Select Folder to Save Downloaded PDFs", #
            initialdir=os.getcwd() #
        )
        if path: #
            self.output_folder_path.set(os.path.normpath(path)) #

    def update_log_area(self, message): #
        self.log_text_area.configure(state='normal') #
        self.log_text_area.insert(tk.END, message + "\n") #
        self.log_text_area.see(tk.END) #
        self.log_text_area.configure(state='disabled') #

    def update_summary_treeview(self, category_key, item_data): #
        parent_iid = self.tree_categories.get(category_key) #
        if parent_iid: #
            doi_val = item_data.get('doi', 'N/A') #
            title_display = (item_data.get('title', 'No Title')[:70] + '...') if len(item_data.get('title', '')) > 73 else item_data.get('title', 'No Title') #
            status_info_val = f"{title_display} -- {item_data.get('status_info', 'N/A')}" #
            url_val = item_data.get('url_info', 'N/A') #
            
            self.summary_tree.insert(parent_iid, tk.END, text=doi_val, values=(doi_val, status_info_val, url_val)) #
            self.summary_tree.see(self.summary_tree.get_children(parent_iid)[-1]) #

    def check_gui_queue(self): #
        try:
            while True: #
                queued_item = self.gui_update_queue.get_nowait() #
                if isinstance(queued_item, dict) and 'type' in queued_item: #
                    if queued_item['type'] == 'log': #
                        self.update_log_area(queued_item['message']) #
                    elif queued_item['type'] == 'summary_add': #
                        self.update_summary_treeview(queued_item['category_key'], queued_item['item_data']) #
                else: #
                    self.update_log_area(str(queued_item)) #
        except queue.Empty: #
            pass #
        self.root.after(100, self.check_gui_queue) #

    def gui_update_callback(self, item_to_log): #
        self.gui_update_queue.put(item_to_log) #

    def start_processing_thread(self): #
        input_file = self.input_file_path.get() #
        output_folder = self.output_folder_path.get() #

        if not input_file: #
            messagebox.showerror("Error", "Please select an input file.") #
            return #
        if not output_folder: #
            messagebox.showerror("Error", "Please select an output folder.") #
            return #
        
        if UNPAYWALL_EMAIL == 'YOUR_EMAIL@example.com' or not UNPAYWALL_EMAIL: #
             messagebox.showerror("Error", "Please set your Unpaywall email at the top of the script (UNPAYWALL_EMAIL variable).") #
             return #

        for category_iid in self.tree_categories.values(): #
            for item_iid in self.summary_tree.get_children(category_iid): #
                self.summary_tree.delete(item_iid) #
        
        self.log_text_area.configure(state='normal') #
        self.log_text_area.delete(1.0, tk.END) #
        self.log_text_area.configure(state='disabled') #
        
        self.gui_update_callback({'type': 'log', 'message': "Starting processing..."}) #
        
        self.start_button.config(text="Processing...", state=tk.DISABLED) #
        self.processing_thread = threading.Thread( #
            target=self.run_backend_task, #
            args=(input_file, output_folder), #
            daemon=True #
        )
        self.processing_thread.start() #

    def run_backend_task(self, input_file, output_folder): #
        try:
            references_from_file = [] #
            with open(input_file, 'r', encoding='utf-8') as f: #
                references_from_file = [line.strip() for line in f if line.strip()] #
            
            if not references_from_file: #
                self.gui_update_callback({'type': 'log', 'message': f"No references found in '{input_file}' or the file is empty."}) #
                self.processing_finished() #
                return #

            process_references_backend(references_from_file, output_folder, self.gui_update_callback) #

        except FileNotFoundError: #
            self.gui_update_callback({'type': 'log', 'message': f"🚨 Error: Input file '{input_file}' not found."}) #
        except Exception as e: #
            self.gui_update_callback({'type': 'log', 'message': f"🚨 An unexpected error occurred in backend processing: {e}"}) #
            import traceback #
            self.gui_update_callback({'type': 'log', 'message': traceback.format_exc()}) #
        finally: #
            self.processing_finished() #
            
    def processing_finished(self): #
        self.root.after(0, lambda: self.start_button.config(text="Start Processing", state=tk.NORMAL)) #
        self.gui_update_callback({'type': 'log', 'message': "\n--- All Processing Finished. Check summary above. ---"}) #

if __name__ == "__main__": #
    root = tk.Tk() #
    app = App(root) #
    root.mainloop() #