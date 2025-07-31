
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

    function getCode(textElem) {
        if (!textElem) {
            textElem = codeEditor; // Use global codeEditor if no specific editor passed
        }
        
        let textToCopy = '';
        if (textElem && typeof textElem.getValue === 'function') {  
            // CodeMirror 5 API  
            textToCopy = textElem.getValue();  
            console.log("📋 Using CodeMirror 5 API for copy");  
        } else if (textElem && textElem.state && textElem.state.doc) {  
            // CodeMirror 6 API  
            textToCopy = textElem.state.doc.toString();  
            console.log("📋 Using CodeMirror 6 API for copy");  
        } else {  
            console.error("❌ Invalid CodeMirror editor instance:", textElem);  
            showToast("Failed to access editor content", "error");  
            return null;  
        }
        return textToCopy;
    }

    function getCodingHint(currentCode, context = '') {
        const conversationId = ConversationManager.activeConversationId;
        if (!conversationId) {
            showToast("No active conversation", "error");
            return;
        }

        // Show loading state
        const hintButton = $('#hint-code-button');
        const originalText = hintButton.text();
        hintButton.prop('disabled', true).text('Getting Hint...');

        // Show modal immediately with loading state
        const modal = $('#hint-modal');
        modal.find('#hint-content').html('');
        modal.find('#hint-status').show();
        modal.find('#hint-status-text').text('Analyzing your code and generating hint...');
        modal.modal('show');

        // Use fetch for streaming
        fetch(`/get_coding_hint/${conversationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                current_code: currentCode,
                context: context
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response;
        })
        .then(response => {
            renderStreamingHint(response, conversationId, modal);
        })
        .catch(error => {
            console.error("❌ Error getting coding hint:", error);
            modal.find('#hint-status').hide();
            modal.find('#hint-content').html(`<div class="alert alert-danger">Failed to get coding hint: ${error.message}</div>`);
            showToast("Failed to get coding hint", "error");
        })
        .finally(() => {
            // Restore button state
            hintButton.prop('disabled', false).text(originalText);
        });
    }

    function getFullSolution(currentCode, context = '') {
        const conversationId = ConversationManager.activeConversationId;
        if (!conversationId) {
            showToast("No active conversation", "error");
            return;
        }

        // Show loading state
        const solutionButton = $('#full-solution-code-button');
        const originalText = solutionButton.text();
        solutionButton.prop('disabled', true).text('Generating Solution...');

        // Show modal immediately with loading state
        const modal = $('#solution-modal');
        modal.find('#solution-content').html('');
        modal.find('#solution-status').show();
        modal.find('#solution-status-text').text('Analyzing problem and generating complete solution...');
        modal.modal('show');

        // Use fetch for streaming
        fetch(`/get_full_solution/${conversationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                current_code: currentCode,
                context: context
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response;
        })
        .then(response => {
            renderStreamingSolution(response, conversationId, modal);
        })
        .catch(error => {
            console.error("❌ Error getting full solution:", error);
            modal.find('#solution-status').hide();
            modal.find('#solution-content').html(`<div class="alert alert-danger">Failed to get full solution: ${error.message}</div>`);
            showToast("Failed to get full solution", "error");
        })
        .finally(() => {
            // Restore button state
            solutionButton.prop('disabled', false).text(originalText);
        });
    }

    function renderStreamingHint(streamingResponse, conversationId, modal) {
        const reader = streamingResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        let contentElement = modal.find('#hint-content');
        let statusElement = modal.find('#hint-status');
        let statusTextElement = modal.find('#hint-status-text');
        
        async function read() {
            try {
                const { value, done } = await reader.read();
                
                if (done) {
                    console.log('Hint streaming complete');
                    // Hide status and show final content
                    statusElement.hide();
                    if (accumulatedText) {
                        renderHintContent(contentElement, accumulatedText);
                    }
                    showToast("Hint generated successfully!", "success");
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                let boundary = buffer.indexOf('\n');
                
                while (boundary !== -1) {
                    const part = JSON.parse(buffer.slice(0, boundary));
                    buffer = buffer.slice(boundary + 1);
                    boundary = buffer.indexOf('\n');
                    
                    if (part.error) {
                        statusElement.hide();
                        contentElement.html(`<div class="alert alert-danger">Error: ${part.status}</div>`);
                        showToast("Failed to generate hint", "error");
                        return;
                    }
                    
                    if (part.text) {
                        accumulatedText += part.text;
                        // Update content with streaming text
                        renderHintContent(contentElement, accumulatedText);
                    }
                    
                    if (part.status) {
                        statusTextElement.text(part.status);
                        console.log("Hint status:", part.status);
                    }
                    
                    if (part.completed) {
                        // Hide status and final render
                        statusElement.hide();
                        renderHintContent(contentElement, part.accumulated_text || accumulatedText);
                        showToast("Hint generated successfully!", "success");
                        return;
                    }
                }
                
                // Continue reading
                setTimeout(read, 10);
                
            } catch (error) {
                console.error("Error in hint streaming:", error);
                statusElement.hide();
                contentElement.html(`<div class="alert alert-danger">Streaming error: ${error.message}</div>`);
                showToast("Failed to stream hint", "error");
            }
        }
        
        read();
    }

    function renderHintContent(element, text) {
        if (typeof marked !== 'undefined' && marked.parse) {
            element.html(marked.parse(text));
        } else {
            // Fallback: display as preformatted text
            element.html('<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>');
        }
    }

    function displayHintModal(hintText) {
        // Use the existing hint modal from HTML
        const modal = $('#hint-modal');
        
        // Set content
        renderHintContent(modal.find('#hint-content'), hintText);
        
        // Show the modal using Bootstrap's modal method
        modal.modal('show');
    }

    function renderStreamingSolution(streamingResponse, conversationId, modal) {
        const reader = streamingResponse.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let accumulatedText = '';
        let contentElement = modal.find('#solution-content');
        let statusElement = modal.find('#solution-status');
        let statusTextElement = modal.find('#solution-status-text');
        
        async function read() {
            try {
                const { value, done } = await reader.read();
                
                if (done) {
                    console.log('Solution streaming complete');
                    // Hide status and show final content
                    statusElement.hide();
                    if (accumulatedText) {
                        renderSolutionContent(contentElement, accumulatedText);
                    }
                    showToast("Solution generated successfully!", "success");
                    return;
                }
                
                buffer += decoder.decode(value, { stream: true });
                let boundary = buffer.indexOf('\n');
                
                while (boundary !== -1) {
                    const part = JSON.parse(buffer.slice(0, boundary));
                    buffer = buffer.slice(boundary + 1);
                    boundary = buffer.indexOf('\n');
                    
                    if (part.error) {
                        statusElement.hide();
                        contentElement.html(`<div class="alert alert-danger">Error: ${part.status}</div>`);
                        showToast("Failed to generate solution", "error");
                        return;
                    }
                    
                    if (part.text) {
                        accumulatedText += part.text;
                        // Update content with streaming text
                        renderSolutionContent(contentElement, accumulatedText);
                    }
                    
                    if (part.status) {
                        statusTextElement.text(part.status);
                        console.log("Solution status:", part.status);
                    }
                    
                    if (part.completed) {
                        // Hide status and final render
                        statusElement.hide();
                        renderSolutionContent(contentElement, part.accumulated_text || accumulatedText);
                        showToast("Solution generated successfully!", "success");
                        return;
                    }
                }
                
                // Continue reading
                setTimeout(read, 10);
                
            } catch (error) {
                console.error("Error in solution streaming:", error);
                statusElement.hide();
                contentElement.html(`<div class="alert alert-danger">Streaming error: ${error.message}</div>`);
                showToast("Failed to stream solution", "error");
            }
        }
        
        read();
    }

    function renderSolutionContent(element, text) {
        if (typeof marked !== 'undefined' && marked.parse) {
            element.html(marked.parse(text));
        } else {
            // Fallback: display as preformatted text
            element.html('<pre>' + text.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '</pre>');
        }
    }

    function displaySolutionModal(solutionText) {
        // Use the existing solution modal from HTML
        const modal = $('#solution-modal');
        
        // Set content
        renderSolutionContent(modal.find('#solution-content'), solutionText);
        
        // Show the modal using Bootstrap's modal method
        modal.modal('show');
    }

    function copySolutionToClipboard() {
        // Extract code blocks from the solution and copy to clipboard
        const solutionContent = $('#solution-content');
        const codeBlocks = solutionContent.find('pre code');
        
        if (codeBlocks.length > 0) {
            // Get the largest code block (likely the main solution)
            let longestCode = '';
            codeBlocks.each(function() {
                const code = $(this).text();
                if (code.length > longestCode.length) {
                    longestCode = code;
                }
            });
            
            // Copy to clipboard using the existing copyToClipboard function
            copyToClipboard(null, longestCode, "text");
            
            showToast("Solution copied to clipboard!", "success");
            $('#solution-modal').modal('hide');
        } else {
            showToast("No code found to copy", "error");
        }
    }

    $('#hint-code-button').on('click', function() {  
        if (codeEditor) {  
            const code = getCode();
            if (code !== null) {
                // Get additional context from the conversation if needed
                const context = "Current coding session - requesting hint";
                getCodingHint(code, context);
            }
        } else {  
            showToast("Editor not initialized", "error");  
        }  
    });

    $('#full-solution-code-button').on('click', function() {  
        if (codeEditor) {  
            const code = getCode();
            if (code !== null) {
                // Get additional context from the conversation if needed
                const context = "Current coding session - requesting complete solution";
                getFullSolution(code, context);
            }
        } else {  
            showToast("Editor not initialized", "error");  
        }  
    });

    // Set up copy solution button handler for the existing HTML modal
    $('#copy-solution-btn').on('click', function() {
        copySolutionToClipboard();
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



