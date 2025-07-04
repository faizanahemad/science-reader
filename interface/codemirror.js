
function setupCodeEditor() {  
    let codeEditor = null; // Store editor instance globally  
    let currentCode = null;
      
    // **Modal Opening Logic**  
    $('#code-editor-modal-open-button').on('click', function() {  
        $('#code-editor-modal').modal('show');  
    });  
      
    // COMPREHENSIVE CodeMirror initialization with ALL fallbacks  
    $('#code-editor-modal').on('shown.bs.modal', function () {  
        if (!codeEditor) {  
            const container = document.getElementById('python-code-editor');  
            var initialCode = `# Advanced Python Code Editor  
def comprehensive_example():  
    """Full-featured Python example with syntax highlighting"""  
    import json  
    import datetime  
    from typing import List, Dict, Optional  
    
    # Type hints and modern Python features  
    def process_data(items: List[int]) -> Dict[str, any]:  
        result = {  
            'processed_at': datetime.datetime.now().isoformat(),  
            'total_items': len(items),  
            'sum': sum(items),  
            'average': sum(items) / len(items) if items else 0,  
            'squares': [x**2 for x in items],  
            'evens': [x for x in items if x % 2 == 0]  
        }  
        return result  
    
    # Example usage  
    sample_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]  
    result = process_data(sample_data)  
    
    print(json.dumps(result, indent=2))  
    return result  

# Start writing your Python code here...  
    `;  
            if (currentCode) {
                initialCode = currentCode;
            }
    
            // **PRIORITY 1**: Try CodeMirror 6 solutions in order  
            const cm6Attempts = [  
                () => window.CodeMirror6?.createEditor(container, initialCode),  
                () => window.CodeMirror6_JSDelivr?.createEditor(container, initialCode),  
                () => window.CodeMirror6_ImportMaps?.createEditor(container, initialCode)  
            ];  
    
            let success = false;  
    
            // Try CodeMirror 6 variants  
            for (let i = 0; i < cm6Attempts.length && !success; i++) {  
                try {  
                    console.log(`🔄 Attempting CodeMirror 6 variant ${i + 1}...`);  
                    codeEditor = cm6Attempts[i]();  
                    if (codeEditor) {  
                        console.log(`✅ CodeMirror 6 variant ${i + 1} successful!`);  
                        success = true;  
                    }  
                } catch (error) {  
                    console.warn(`⚠️ CodeMirror 6 variant ${i + 1} failed:`, error.message);  
                }  
            }  
    
            // **PRIORITY 2**: Fallback to CodeMirror 5  
            if (!success && window.CodeMirror5) {  
                try {  
                    console.log("🔄 Falling back to CodeMirror 5...");  
                    codeEditor = window.CodeMirror5.createEditor(container, initialCode);  
                    console.log("✅ CodeMirror 5 successful!");  
                    success = true;  
                } catch (error) {  
                    console.warn("⚠️ CodeMirror 5 failed:", error.message);  
                }  
            }  
    
            // **PRIORITY 3**: Basic CodeMirror 5 (if available)  
            if (!success && window.CodeMirror) {  
                try {  
                    console.log("🔄 Using basic CodeMirror 5...");  
                    container.innerHTML = '<textarea class="form-control" rows="20"></textarea>';  
                    const textarea = container.querySelector('textarea');  
                    textarea.value = initialCode;  
    
                    codeEditor = CodeMirror.fromTextArea(textarea, {  
                        mode: 'python',  
                        lineNumbers: true,  
                        theme: 'default',  
                        lineWrapping: true  
                    });  
                    console.log("✅ Basic CodeMirror 5 successful!");  
                    success = true;  
                } catch (error) {  
                    console.warn("⚠️ Basic CodeMirror 5 failed:", error.message);  
                }  
            }  
    
            // **LAST RESORT**: Plain textarea  
            if (!success) {  
                console.error("💥 All CodeMirror approaches failed!");  
                container.innerHTML = `  
                    <div class="alert alert-danger mb-2">  
                        <strong>⚠️ All CodeMirror Variants Failed</strong><br>  
                        <small>Using basic textarea. No syntax highlighting available.</small>  
                    </div>  
                    <textarea class="form-control" rows="20"  
                            placeholder="All CodeMirror variants failed. Basic editing available..."  
                            style="font-family: 'Courier New', monospace; font-size: 14px;">${initialCode}</textarea>  
                `;  
    
                codeEditor = {  
                    getValue: () => container.querySelector('textarea').value,  
                    setValue: (val) => container.querySelector('textarea').value = val,  
                    focus: () => container.querySelector('textarea').focus()  
                };  
            }  
        }  
    
        // Focus the editor  
        setTimeout(() => {  
            if (codeEditor && codeEditor.focus) {  
                codeEditor.focus();  
            }  
        }, 100);  
    });  

    // on modal close, save the code to the server
    $('#code-editor-modal').on('hidden.bs.modal', function() {
        const code = codeEditor.getValue();
        currentCode = code;
    });





    
    



        
        // **Copy Code Button** - Fixed for CodeMirror 5  
    $('#copy-code-button').on('click', function() {  
        if (codeEditor) {  
            copyToClipboard(codeEditor, undefined, "codemirror");  
        } else {  
            showToast("Editor not initialized", "error");  
        }  
    });  
    
    
    
    // **Clear Code Button** - Fixed for CodeMirror 5  
    $('#clear-code-button').on('click', function() {  
        if (codeEditor) {  
            if (confirm("Are you sure you want to clear all code?")) {  
                codeEditor.setValue("# Start typing your Python code here...\n");  
                showToast("Code cleared", "info");  
            }  
        }  
    });  
    
    // **Format Code Button** - Fixed for CodeMirror 5  
    $('#format-code-button').on('click', function() {  
        if (codeEditor) {  
            const currentCode = codeEditor.getValue(); // CodeMirror 5 API  
            const formattedCode = formatPythonCode(currentCode);  
            codeEditor.setValue(formattedCode); // CodeMirror 5 API  
            showToast("Code formatted", "success");  
        }  
    });  
    
    // **Save Code Button** - Fixed for CodeMirror 5  
    $('#save-code-button').on('click', function() {  
        if (codeEditor) {  
            const code = codeEditor.getValue(); // CodeMirror 5 API  
            saveCodeToServer(code);  
            $('#code-editor-modal').modal('hide');  
        }  
    });  

    function runCodeAndShowResults() {  
        console.log("🚀 Starting code execution and results display...");  
          
        // Get code from editor  
        const code = codeEditor.getValue();  
          
        if (!code || code.trim() === '') {  
            showToast("Please enter some code to execute", "warning");  
            return;  
        }  
          
        // Show results modal immediately with loading state  
        $('#code-results-modal').modal('show');  
        $('#results-loading').removeClass('d-none');  
        $('#results-content').addClass('d-none');  
        $('#results-error').addClass('d-none');  
          
        // Execute the API call  
        $.ajax({  
            url: '/run_code_once',  
            method: 'POST',  
            contentType: 'application/json',  
            data: JSON.stringify({  
                code_string: code  
            }),  
            success: function(response) {  
                console.log("✅ Code execution successful");  
                  
                // Hide loading state  
                $('#results-loading').addClass('d-none');  
                  
                // Show results content  
                $('#results-content').removeClass('d-none');  
                  
                // Set the raw response as text content first  
                $('#results-content').text(response);  
                  
                // Create jQuery element and render as markdown  
                const $resultsElement = $('#results-content');  
                  
                try {  
                    // Call your existing markdown rendering function  
                    renderInnerContentAsMarkdown($resultsElement);  
                    console.log("✅ Markdown rendering completed");  
                      
                    // Show success toast  
                    showToast("Code executed successfully!", "success");  
                      
                } catch (markdownError) {  
                    console.warn("⚠️ Markdown rendering failed, showing as plain text:", markdownError);  
                    // If markdown rendering fails, show as preformatted text  
                    $('#results-content').html(`<pre>${response}</pre>`);  
                    showToast("Code executed (plain text display)", "info");  
                }  
            },  
            error: function(xhr, status, error) {  
                console.error("💥 Code execution failed:", error);  
                  
                // Hide loading state  
                $('#results-loading').addClass('d-none');  
                  
                // Show error state  
                $('#results-error').removeClass('d-none');  
                  
                // Display error details  
                const errorMessage = xhr.responseJSON?.error || xhr.responseText || error;  
                $('#error-details').text(errorMessage);  
                  
                showToast("Code execution failed", "error");  
            },  
            timeout: 30000 // 30 second timeout for long-running code  
        });  
    }  

    $('#run-code-button').on('click', function() {  
        runCodeAndShowResults(); // Use the single method  
    });  
      
    // Add copy results functionality  
    $('#copy-results-button').on('click', function() {  
        const resultsText = $('#results-content').text();  
        if (resultsText) {  
            copyToClipboard(null, resultsText, "text");  
        } else {  
            showToast("No results to copy", "warning");  
        }  
    });  
    
}
  
// **Helper Functions**  
  
// Basic Python code formatting function  
function formatPythonCode(code) {  
    // Very basic formatting - you can enhance this  
    const lines = code.split('\n');  
    let indentLevel = 0;  
    const formatted = [];  
      
    lines.forEach(line => {  
        const trimmed = line.trim();  
        if (trimmed === '') {  
            formatted.push('');  
            return;  
        }  
          
        // Decrease indent for certain keywords  
        if (trimmed.match(/^(except|elif|else|finally):/)) {  
            indentLevel = Math.max(0, indentLevel - 1);  
        }  
          
        // Add current line with proper indentation  
        formatted.push('    '.repeat(indentLevel) + trimmed);  
          
        // Increase indent after certain keywords  
        if (trimmed.match(/^(if|elif|else|for|while|def|class|try|except|finally|with).*:$/)) {  
            indentLevel++;  
        }  
    });  
      
    return formatted.join('\n');  
}  
  
// Function to save code to your Flask server  
function saveCodeToServer(code) {  
    // Example AJAX call to your Flask backend  
    $.ajax({  
        url: '/save-code', // Your Flask endpoint  
        method: 'POST',  
        contentType: 'application/json',  
        data: JSON.stringify({  
            code: code,  
            timestamp: new Date().toISOString()  
        }),  
        success: function(response) {  
            showToast("Code saved successfully!", "success");  
        },  
        error: function(xhr, status, error) {  
            showToast("Failed to save code", "error");  
            console.error("Save error:", error);  
        }  
    });  
}  



