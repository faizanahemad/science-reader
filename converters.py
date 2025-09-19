import os  
import requests  
import traceback  
import logging  
  
logger = logging.getLogger(__name__)  
  
def convert_html_to_pdf(file_path, output_path):  
    """  
    Convert HTML file to PDF using Gotenberg's Chromium engine.  
      
    Args:  
        file_path (str): Path to the HTML file  
        output_path (str): Path where the PDF will be saved  
          
    Returns:  
        bool: True if conversion successful, False otherwise  
    """  
    # Gotenberg Chromium endpoint for HTML conversion  
    GOTENBERG_BASE_URL = os.getenv("PDF_CONVERT_URL", "http://localhost:7777")  
    api_url = f"{GOTENBERG_BASE_URL}/forms/chromium/convert/html"  
      
    try:  
        logger.info(f"Converting HTML at {file_path} to PDF, file exists = {os.path.exists(file_path)}")  
        assert os.path.exists(file_path), f"HTML file not found: {file_path}"  
          
        # Validate file extension  
        if not file_path.lower().endswith(('.html', '.htm')):  
            raise ValueError(f"Expected HTML file, got: {file_path}")  
          
        with open(file_path, 'rb') as f:  
            files = {'files': (os.path.basename(file_path), f, 'text/html')}  
              
            # Gotenberg Chromium-specific parameters  
            payload = {  
                'paperWidth': '8.27',      # A4 width in inches  
                'paperHeight': '11.7',     # A4 height in inches  
                'marginTop': '0.39',       # 1cm margin  
                'marginBottom': '0.39',  
                'marginLeft': '0.39',  
                'marginRight': '0.39',  
                'preferCSSPageSize': 'false',  
                'printBackground': 'true',  
                'landscape': 'false',  
                'scale': '1.0'  
            }  
              
            logger.info(f"Sending HTML conversion request to: {api_url}")  
            response = requests.post(  
                api_url,   
                files=files,   
                data=payload,  
                timeout=60  # 60 second timeout  
            )  
              
            if response.status_code == 200:  
                # Ensure output directory exists  
                os.makedirs(os.path.dirname(output_path), exist_ok=True)  
                  
                with open(output_path, 'wb') as out_file:  
                    out_file.write(response.content)  
                  
                logger.info(f"✅ HTML to PDF conversion successful: {output_path}")  
                return True  
            else:  
                logger.error(f"❌ HTML conversion failed with status {response.status_code}: {response.text}")  
                return False  
                  
    except Exception as e:  
        exc = traceback.format_exc()  
        logger.error(f"❌ Exception converting HTML at {file_path} to PDF: {e}\n{exc}")  
        return False  


def convert_doc_to_pdf(file_path, output_path):  
    """  
    Convert DOCX/DOC file to PDF using Gotenberg's LibreOffice engine.  
      
    Args:  
        file_path (str): Path to the DOCX/DOC file  
        output_path (str): Path where the PDF will be saved  
          
    Returns:  
        bool: True if conversion successful, False otherwise  
    """  
    # Gotenberg LibreOffice endpoint for Office document conversion  
    GOTENBERG_BASE_URL = os.getenv("PDF_CONVERT_URL", "http://localhost:7777")  
    api_url = f"{GOTENBERG_BASE_URL}/forms/libreoffice/convert"  
      
    try:  
        logger.info(f"Converting DOCX at {file_path} to PDF, file exists = {os.path.exists(file_path)}")  
        assert os.path.exists(file_path), f"DOCX file not found: {file_path}"  
          
        # Validate file extension  
        supported_extensions = ('.docx', '.doc', '.odt', '.rtf', '.xlsx', '.xls', '.pptx', '.ppt')  
        if not file_path.lower().endswith(supported_extensions):  
            raise ValueError(f"Unsupported file type. Expected: {supported_extensions}, got: {file_path}")  
          
        # Determine MIME type based on extension  
        mime_types = {  
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',  
            '.doc': 'application/msword',  
            '.odt': 'application/vnd.oasis.opendocument.text',  
            '.rtf': 'application/rtf',  
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  
            '.xls': 'application/vnd.ms-excel',  
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',  
            '.ppt': 'application/vnd.ms-powerpoint'  
        }  
          
        file_ext = os.path.splitext(file_path)[1].lower()  
        mime_type = mime_types.get(file_ext, 'application/octet-stream')  
          
        with open(file_path, 'rb') as f:  
            files = {'files': (os.path.basename(file_path), f, mime_type)}  
              
            # Gotenberg LibreOffice-specific parameters  
            payload = {  
                'pdfFormat': 'PDF/A-1a',           # PDF/A format for archival  
                'merge': 'false',                  # Don't merge multiple files  
                'landscape': 'false',              # Portrait orientation  
                'nativePageRanges': '',            # Convert all pages  
                'exportFormFields': 'true',        # Include form fields  
                'allowDuplicateFieldNames': 'false',  
                'exportBookmarks': 'true',         # Include bookmarks  
                'exportBookmarksToPdfDestination': 'false',  
                'exportPlaceholders': 'false',  
                'exportNotes': 'false',  
                'exportNotesPages': 'false',  
                'exportOnlyNotesPages': 'false',  
                'exportNotesInMargin': 'false',  
                'convertOooTargetToPdfTarget': 'false',  
                'exportLinksRelativeFsys': 'false',  
                'exportHiddenSlides': 'false',  
                'skipEmptyPages': 'true',  
                'addOriginalDocumentAsStream': 'false'  
            }  
              
            logger.info(f"Sending DOCX conversion request to: {api_url}")  
            response = requests.post(  
                api_url,   
                files=files,   
                data=payload,  
                timeout=120  # 2 minute timeout for larger documents  
            )  
              
            if response.status_code == 200:  
                # Ensure output directory exists  
                os.makedirs(os.path.dirname(output_path), exist_ok=True)  
                  
                with open(output_path, 'wb') as out_file:  
                    out_file.write(response.content)  
                  
                logger.info(f"✅ DOCX to PDF conversion successful: {output_path}")  
                return True  
            else:  
                logger.error(f"❌ DOCX conversion failed with status {response.status_code}: {response.text}")  
                return False  
                  
    except Exception as e:  
        exc = traceback.format_exc()  
        logger.error(f"❌ Exception converting DOCX at {file_path} to PDF: {e}\n{exc}")  
        return False  


def batch_convert_documents(file_list, output_dir):  
    """  
    Convert multiple documents to PDF using appropriate conversion function.  
      
    Args:  
        file_list (list): List of file paths to convert  
        output_dir (str): Directory to save converted PDFs  
          
    Returns:  
        dict: Conversion results with success/failure counts  
    """  
    results = {"success": 0, "failed": 0, "errors": []}  
      
    for file_path in file_list:  
        try:  
            # Determine output path  
            base_name = os.path.splitext(os.path.basename(file_path))[0]  
            output_path = os.path.join(output_dir, f"{base_name}.pdf")  
              
            # Choose appropriate conversion function  
            if file_path.lower().endswith(('.html', '.htm')):  
                success = convert_html_to_pdf(file_path, output_path)  
            elif file_path.lower().endswith(('.docx', '.doc', '.odt', '.rtf')):  
                success = convert_doc_to_pdf(file_path, output_path)  
            else:  
                results["errors"].append(f"Unsupported file type: {file_path}")  
                results["failed"] += 1  
                continue  
              
            if success:  
                results["success"] += 1  
            else:  
                results["failed"] += 1  
                results["errors"].append(f"Conversion failed: {file_path}")  
                  
        except Exception as e:  
            results["failed"] += 1  
            results["errors"].append(f"Error processing {file_path}: {str(e)}")  
      
    return results 