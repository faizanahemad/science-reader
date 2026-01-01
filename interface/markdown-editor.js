/**
 * Markdown Editor Manager
 * 
 * Provides multiple markdown editor implementations for the message edit modal:
 * - CodeMirror + Preview: Syntax highlighted editor with preview tab
 * - EasyMDE: Full-featured markdown editor with toolbar
 * - WYSIWYG: Edit rendered markdown directly using ContentEditable
 * 
 * Features:
 * - Tabbed interface for code/preview switching
 * - Scroll position sync between tabs
 * - UI selector to switch between editor types
 * - Consistent API for getting/setting content
 */

var MarkdownEditorManager = (function() {
    'use strict';
    
    // Private state
    var currentEditorType = 'codemirror-preview'; // Default
    var editors = {
        codemirror: null,
        easymde: null,
        wysiwyg: null
    };
    var currentText = '';
    var initialText = ''; // Store the text passed to openEditor
    var scrollPositions = {
        code: { top: 0, percentage: 0 },
        preview: { top: 0, percentage: 0 }
    };
    var isInitialized = false;
    var hasEditorBeenInitialized = false; // Track if any editor has been created
    
    /**
     * Initialize the editor manager
     * Sets up event listeners for editor type switching and tab changes
     */
    function init() {
        if (isInitialized) return;
        
        // Listen for editor type changes
        $('#message-edit-editor-type').on('change', function() {
            var newType = $(this).val();
            // Save current content before switching
            if (hasEditorBeenInitialized) {
                currentText = getValue();
            }
            switchEditorType(newType);
        });
        
        // Listen for tab switches to sync scroll position
        $('#message-edit-tabs a[data-toggle="tab"]').on('shown.bs.tab', function(e) {
            var targetPane = $(e.target).attr('href');
            if (targetPane === '#edit-preview-pane') {
                // Switching to preview - update preview content and restore scroll
                updatePreview();
                setTimeout(function() {
                    restoreScrollPosition('preview');
                }, 50);
            } else {
                // Switching to code - restore scroll
                setTimeout(function() {
                    restoreScrollPosition('code');
                }, 50);
            }
        });
        
        // Handle modal hide - cleanup
        $('#message-edit-modal').on('hidden.bs.modal', function() {
            resetScrollPositions();
        });
        
        isInitialized = true;
        console.log('MarkdownEditorManager initialized');
    }
    
    /**
     * Save current scroll position for a pane
     * @param {string} pane - 'code' or 'preview'
     */
    function saveScrollPosition(pane) {
        if (pane === 'code') {
            var editor = getActiveCodeMirror();
            if (editor) {
                var scrollInfo = editor.getScrollInfo();
                scrollPositions.code.top = scrollInfo.top;
                var maxScroll = scrollInfo.height - scrollInfo.clientHeight;
                scrollPositions.code.percentage = maxScroll > 0 ? scrollInfo.top / maxScroll : 0;
            }
        } else {
            var element = $('#message-edit-preview');
            if (element.length && element[0].scrollHeight > element.innerHeight()) {
                var scrollTop = element.scrollTop();
                var maxScroll = element[0].scrollHeight - element.innerHeight();
                scrollPositions.preview.top = scrollTop;
                scrollPositions.preview.percentage = maxScroll > 0 ? scrollTop / maxScroll : 0;
            }
        }
    }
    
    /**
     * Get the active CodeMirror instance based on current editor type
     */
    function getActiveCodeMirror() {
        switch (currentEditorType) {
            case 'codemirror-preview':
                return editors.codemirror;
            case 'easymde':
                return editors.easymde ? editors.easymde.codemirror : null;
            default:
                return null;
        }
    }
    
    /**
     * Restore scroll position for a pane based on percentage
     * @param {string} pane - 'code' or 'preview'
     */
    function restoreScrollPosition(pane) {
        // Use the opposite pane's percentage to calculate scroll position
        var sourcePercentage = pane === 'code' ? scrollPositions.preview.percentage : scrollPositions.code.percentage;
        
        if (pane === 'code') {
            var editor = getActiveCodeMirror();
            if (editor) {
                var scrollInfo = editor.getScrollInfo();
                var maxScroll = scrollInfo.height - scrollInfo.clientHeight;
                var targetTop = sourcePercentage * maxScroll;
                editor.scrollTo(null, targetTop);
            }
        } else {
            var element = $('#message-edit-preview');
            if (element.length) {
                var maxScroll = element[0].scrollHeight - element.innerHeight();
                var targetTop = sourcePercentage * maxScroll;
                element.scrollTop(targetTop);
            }
        }
    }
    
    /**
     * Reset scroll positions
     */
    function resetScrollPositions() {
        scrollPositions = {
            code: { top: 0, percentage: 0 },
            preview: { top: 0, percentage: 0 }
        };
    }
    
    /**
     * Switch to a different editor type
     * @param {string} editorType - One of: 'codemirror-preview', 'easymde', 'milkdown'
     */
    function switchEditorType(editorType) {
        console.log('Switching to editor type:', editorType, 'Current text length:', currentText.length);
        
        // Hide all editor containers
        $('#message-edit-codemirror-container').hide();
        $('#message-edit-easymde-container').hide();
        $('#message-edit-milkdown-container').hide();
        $('#message-edit-text').hide();
        
        // Update current type
        currentEditorType = editorType;
        
        // Show/hide tabs based on editor type
        if (editorType === 'milkdown') {
            // WYSIWYG - no tabs needed
            $('#message-edit-tabs').hide();
            $('#message-edit-scroll-info').hide();
            $('#edit-code-tab').tab('show');
        } else {
            // Tabbed editors
            $('#message-edit-tabs').show();
            $('#message-edit-scroll-info').show();
            $('#edit-code-tab').tab('show');
        }
        
        // Initialize and show the appropriate editor
        switch (editorType) {
            case 'codemirror-preview':
                initCodeMirror();
                break;
            case 'easymde':
                initEasyMDE();
                break;
            case 'milkdown':
                initWYSIWYG();
                break;
        }
        
        // Set the content after initialization
        setValue(currentText);
        hasEditorBeenInitialized = true;
    }
    
    /**
     * Initialize EasyMDE (Option 2)
     * Full-featured markdown editor with toolbar
     */
    function initEasyMDE() {
        var container = $('#message-edit-easymde-container');
        container.show();
        
        if (!editors.easymde) {
            editors.easymde = new EasyMDE({
                element: document.getElementById('message-edit-text-easymde'),
                spellChecker: false,
                autofocus: false,
                status: false,
                minHeight: '400px',
                toolbar: [
                    'bold', 'italic', 'heading', '|',
                    'quote', 'code', 'unordered-list', 'ordered-list', '|',
                    'link', 'image', 'table', '|',
                    'undo', 'redo'
                ],
                previewRender: function(plainText) {
                    // Use the project's existing marked.js renderer
                    if (typeof marked !== 'undefined') {
                        return marked.parse(plainText);
                    }
                    return plainText;
                }
            });
            
            // Handle scroll for sync
            editors.easymde.codemirror.on('scroll', function() {
                saveScrollPosition('code');
            });
        }
        
        setTimeout(function() {
            editors.easymde.codemirror.refresh();
        }, 10);
    }
    
    /**
     * Initialize CodeMirror with Preview tabs
     * CodeMirror editor with tabbed preview using project's markdown renderer
     */
    function initCodeMirror() {
        var container = document.getElementById('message-edit-codemirror-container');
        $(container).show();
        
        if (!editors.codemirror) {
            container.innerHTML = '';
            var textarea = document.createElement('textarea');
            container.appendChild(textarea);
            
            editors.codemirror = CodeMirror.fromTextArea(textarea, {
                mode: 'gfm',
                theme: 'monokai',
                lineNumbers: true,
                lineWrapping: true,
                autoCloseBrackets: true,
                matchBrackets: true,
                styleActiveLine: true,
                foldGutter: true,
                gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
                extraKeys: {
                    'Ctrl-B': function(cm) { wrapSelection(cm, '**'); },
                    'Ctrl-I': function(cm) { wrapSelection(cm, '*'); },
                    'Ctrl-K': function(cm) { insertLink(cm); }
                }
            });
            
            // Handle scroll events for sync
            editors.codemirror.on('scroll', function() {
                saveScrollPosition('code');
            });
            
            // Set height
            editors.codemirror.setSize('100%', '100%');
        }
        
        setTimeout(function() {
            editors.codemirror.refresh();
        }, 10);
    }
    
    /**
     * Initialize WYSIWYG Editor (Option 5)
     * Uses ContentEditable with HTML to Markdown conversion
     * This is a simpler, more reliable approach than Milkdown
     */
    function initWYSIWYG() {
        var container = document.getElementById('message-edit-milkdown-container');
        $(container).show().empty();
        
        // Create a toolbar
        var toolbar = $('<div class="wysiwyg-toolbar mb-1 p-1 bg-light border-bottom d-flex flex-wrap"></div>');
        toolbar.html(`
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="bold" title="Bold (Ctrl+B)"><b>B</b></button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="italic" title="Italic (Ctrl+I)"><i>I</i></button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="insertUnorderedList" title="Bullet List">•</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="insertOrderedList" title="Numbered List">1.</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="formatBlock" data-value="h2" title="Heading">H</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="formatBlock" data-value="blockquote" title="Quote">"</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="createLink" title="Insert Link">🔗</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mr-1 mb-1" data-command="inlineCode" title="Inline Code">&lt;/&gt;</button>
            <button type="button" class="btn btn-xs btn-outline-secondary mb-1" data-command="codeBlock" title="Code Block">{ }</button>
        `);
        
        // Create contenteditable area
        var editorArea = $('<div id="wysiwyg-editor" class="wysiwyg-editor p-3" contenteditable="true"></div>');
        editorArea.css({
            'min-height': '400px',
            'max-height': 'calc(65vh - 100px)',
            'overflow-y': 'auto',
            'border': '1px solid #dee2e6',
            'border-radius': '0.25rem',
            'background': '#fff',
            'outline': 'none'
        });
        
        $(container).append(toolbar);
        $(container).append(editorArea);
        
        // Toolbar button handlers
        toolbar.find('button').on('click', function(e) {
            e.preventDefault();
            var command = $(this).data('command');
            var value = $(this).data('value') || null;
            
            if (command === 'createLink') {
                value = prompt('Enter URL:', 'https://');
                if (!value) return;
                document.execCommand(command, false, value);
            } else if (command === 'inlineCode') {
                // Wrap selection in <code> tag
                var selection = window.getSelection();
                if (selection.rangeCount > 0) {
                    var range = selection.getRangeAt(0);
                    var selectedText = range.toString();
                    var code = document.createElement('code');
                    code.textContent = selectedText || 'code';
                    range.deleteContents();
                    range.insertNode(code);
                    // Move cursor after the code element
                    range.setStartAfter(code);
                    range.setEndAfter(code);
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
            } else if (command === 'codeBlock') {
                // Insert a code block
                var selection = window.getSelection();
                if (selection.rangeCount > 0) {
                    var range = selection.getRangeAt(0);
                    var selectedText = range.toString();
                    var pre = document.createElement('pre');
                    var code = document.createElement('code');
                    code.textContent = selectedText || '// code here';
                    pre.appendChild(code);
                    range.deleteContents();
                    range.insertNode(pre);
                    // Add a paragraph after for continued editing
                    var p = document.createElement('p');
                    p.innerHTML = '<br>';
                    pre.parentNode.insertBefore(p, pre.nextSibling);
                    // Move cursor to the code
                    range.selectNodeContents(code);
                    selection.removeAllRanges();
                    selection.addRange(range);
                }
            } else {
                document.execCommand(command, false, value);
            }
            editorArea.focus();
        });
        
        // Store reference
        editors.wysiwyg = editorArea;
    }
    
    /**
     * Convert HTML to Markdown (simple implementation)
     */
    function htmlToMarkdown(html) {
        // Create a temporary element
        var temp = document.createElement('div');
        temp.innerHTML = html;
        
        // Process the content
        var markdown = processNode(temp);
        
        // Clean up extra whitespace
        markdown = markdown.replace(/\n{3,}/g, '\n\n').trim();
        
        return markdown;
    }
    
    /**
     * Process a DOM node and convert to markdown
     */
    function processNode(node) {
        var result = '';
        
        for (var i = 0; i < node.childNodes.length; i++) {
            var child = node.childNodes[i];
            
            if (child.nodeType === 3) { // Text node
                result += child.textContent;
            } else if (child.nodeType === 1) { // Element node
                var tag = child.tagName.toLowerCase();
                var content = processNode(child);
                
                switch (tag) {
                    case 'b':
                    case 'strong':
                        result += '**' + content + '**';
                        break;
                    case 'i':
                    case 'em':
                        result += '*' + content + '*';
                        break;
                    case 'h1':
                        result += '\n# ' + content + '\n';
                        break;
                    case 'h2':
                        result += '\n## ' + content + '\n';
                        break;
                    case 'h3':
                        result += '\n### ' + content + '\n';
                        break;
                    case 'h4':
                        result += '\n#### ' + content + '\n';
                        break;
                    case 'h5':
                        result += '\n##### ' + content + '\n';
                        break;
                    case 'h6':
                        result += '\n###### ' + content + '\n';
                        break;
                    case 'p':
                        result += '\n' + content + '\n';
                        break;
                    case 'br':
                        result += '\n';
                        break;
                    case 'a':
                        var href = child.getAttribute('href') || '';
                        result += '[' + content + '](' + href + ')';
                        break;
                    case 'img':
                        var src = child.getAttribute('src') || '';
                        var alt = child.getAttribute('alt') || '';
                        result += '![' + alt + '](' + src + ')';
                        break;
                    case 'ul':
                        result += '\n' + processListItems(child, '- ') + '\n';
                        break;
                    case 'ol':
                        result += '\n' + processListItems(child, null, true) + '\n';
                        break;
                    case 'li':
                        result += content;
                        break;
                    case 'blockquote':
                        result += '\n> ' + content.replace(/\n/g, '\n> ') + '\n';
                        break;
                    case 'code':
                        if (child.parentElement && child.parentElement.tagName.toLowerCase() === 'pre') {
                            result += content;
                        } else {
                            result += '`' + content + '`';
                        }
                        break;
                    case 'pre':
                        result += '\n```\n' + content + '\n```\n';
                        break;
                    case 'hr':
                        result += '\n---\n';
                        break;
                    case 'div':
                    case 'span':
                        result += content;
                        break;
                    default:
                        result += content;
                }
            }
        }
        
        return result;
    }
    
    /**
     * Process list items
     */
    function processListItems(listNode, prefix, ordered) {
        var result = '';
        var count = 1;
        
        for (var i = 0; i < listNode.childNodes.length; i++) {
            var child = listNode.childNodes[i];
            if (child.nodeType === 1 && child.tagName.toLowerCase() === 'li') {
                var content = processNode(child).trim();
                if (ordered) {
                    result += count + '. ' + content + '\n';
                    count++;
                } else {
                    result += prefix + content + '\n';
                }
            }
        }
        
        return result;
    }
    
    /**
     * Update the preview pane with rendered markdown
     */
    function updatePreview() {
        var markdown = getValue();
        var previewPane = $('#message-edit-preview');
        
        // Use the project's markdown renderer
        try {
            var html = '';
            if (typeof marked !== 'undefined') {
                html = marked.parse(markdown);
            } else {
                html = '<pre>' + markdown + '</pre>';
            }
            previewPane.html(html);
            
            // Apply syntax highlighting to code blocks
            if (typeof hljs !== 'undefined') {
                previewPane.find('pre code').each(function() {
                    hljs.highlightElement(this);
                });
            }
            
            // Render math if MathJax is available
            if (typeof MathJax !== 'undefined' && MathJax.Hub) {
                MathJax.Hub.Queue(['Typeset', MathJax.Hub, previewPane[0]]);
            }
            
            // Render mermaid diagrams if available
            if (typeof mermaid !== 'undefined') {
                previewPane.find('pre.mermaid, code.language-mermaid').each(function() {
                    var code = $(this).text();
                    var id = 'mermaid-' + Math.random().toString(36).substr(2, 9);
                    $(this).replaceWith('<div class="mermaid" id="' + id + '">' + code + '</div>');
                });
                try {
                    mermaid.run({ querySelector: '#message-edit-preview .mermaid' });
                } catch (e) {
                    console.warn('Mermaid rendering failed:', e);
                }
            }
        } catch (error) {
            console.error('Error rendering preview:', error);
            previewPane.html('<div class="alert alert-danger">Error rendering preview: ' + error.message + '</div>');
        }
    }
    
    /**
     * Get the current value from the active editor
     * @returns {string} The markdown content
     */
    function getValue() {
        switch (currentEditorType) {
            case 'codemirror-preview':
                return editors.codemirror ? editors.codemirror.getValue() : currentText;
            case 'easymde':
                return editors.easymde ? editors.easymde.value() : currentText;
            case 'milkdown':
                if (editors.wysiwyg && editors.wysiwyg.length) {
                    return htmlToMarkdown(editors.wysiwyg.html());
                }
                return currentText;
            default:
                return $('#message-edit-text').val() || currentText;
        }
    }
    
    /**
     * Set the value in the active editor
     * @param {string} text - The markdown content to set
     */
    function setValue(text) {
        var textToSet = text || '';
        console.log('Setting value, text length:', textToSet.length, 'editor type:', currentEditorType);
        
        switch (currentEditorType) {
            case 'codemirror-preview':
                if (editors.codemirror) {
                    editors.codemirror.setValue(textToSet);
                    setTimeout(function() {
                        editors.codemirror.refresh();
                    }, 10);
                }
                break;
            case 'easymde':
                if (editors.easymde) {
                    editors.easymde.value(textToSet);
                    setTimeout(function() {
                        editors.easymde.codemirror.refresh();
                    }, 10);
                }
                break;
            case 'milkdown':
                if (editors.wysiwyg && editors.wysiwyg.length) {
                    // Convert markdown to HTML for WYSIWYG
                    var html = '';
                    if (typeof marked !== 'undefined') {
                        html = marked.parse(textToSet);
                    } else {
                        html = textToSet.replace(/\n/g, '<br>');
                    }
                    editors.wysiwyg.html(html);
                }
                break;
            default:
                $('#message-edit-text').val(textToSet);
        }
    }
    
    /**
     * Refresh the current editor (useful after modal is shown)
     */
    function refreshCurrentEditor() {
        setTimeout(function() {
            switch (currentEditorType) {
                case 'codemirror-preview':
                    if (editors.codemirror) {
                        editors.codemirror.refresh();
                    }
                    break;
                case 'easymde':
                    if (editors.easymde) {
                        editors.easymde.codemirror.refresh();
                    }
                    break;
            }
        }, 50);
    }
    
    /**
     * Open the editor modal with the given text
     * @param {string} text - The markdown content to edit
     * @param {function} onSave - Callback function when save is clicked, receives new text
     */
    function openEditor(text, onSave) {
        init(); // Ensure initialized
        
        // Store the text to edit
        currentText = text || '';
        initialText = currentText;
        hasEditorBeenInitialized = false;
        
        // CRITICAL: Store the onSave callback in a variable that won't be overwritten
        // by subsequent openEditor calls. This prevents the bug where editing card A,
        // then editing card B, causes A to be overwritten with B's content.
        var pendingSaveCallback = onSave;

        // Preload the current editor instance (if it already exists) with the new text
        // BEFORE the modal becomes visible. This prevents a brief flash of the previous
        // message content when reopening the modal.
        try {
            if (currentEditorType === 'codemirror-preview' && editors.codemirror) {
                editors.codemirror.setValue(currentText);
            } else if (currentEditorType === 'easymde' && editors.easymde) {
                editors.easymde.value(currentText);
                editors.easymde.codemirror.refresh();
            } else if (currentEditorType === 'milkdown' && editors.wysiwyg && editors.wysiwyg.length) {
                var html = (typeof marked !== 'undefined') ? marked.parse(currentText) : currentText.replace(/\n/g, '<br>');
                editors.wysiwyg.html(html);
            }
        } catch (preloadErr) {
            console.warn('Preload editor value failed:', preloadErr);
        }
        
        console.log('Opening editor with text length:', currentText.length);
        
        // Get saved editor preference or use default
        var savedType = localStorage.getItem('message-edit-editor-type');
        if (savedType) {
            currentEditorType = savedType;
            $('#message-edit-editor-type').val(savedType);
        }
        
        // Remove any pending modal event handlers to prevent stale callbacks
        $('#message-edit-modal').off('shown.bs.modal.editorInit');
        $('#message-edit-text-save-button').off('click.editorSave');
        
        // Show modal first (editor needs visible container)
        $('#message-edit-modal').modal('show');
        
        // Initialize editor after modal is shown (namespaced event to avoid conflicts)
        $('#message-edit-modal').one('shown.bs.modal.editorInit', function() {
            console.log('Modal shown, initializing editor type:', currentEditorType);
            switchEditorType(currentEditorType);
            
            // Store editor type preference on change
            $('#message-edit-editor-type').off('change.savePreference').on('change.savePreference', function() {
                localStorage.setItem('message-edit-editor-type', $(this).val());
            });
        });
        
        // Set up save handler with namespaced event and captured callback
        $('#message-edit-text-save-button').on('click.editorSave', function() {
            var newText = getValue();
            var callbackToUse = pendingSaveCallback; // Capture in local scope
            console.log('Saving, new text length:', newText.length);
            
            // Remove handler immediately to prevent double-fires
            $('#message-edit-text-save-button').off('click.editorSave');
            
            $('#message-edit-modal').modal('hide');
            if (typeof callbackToUse === 'function') {
                callbackToUse(newText);
            }
        });
    }
    
    /**
     * Helper: Wrap selected text with given characters
     */
    function wrapSelection(cm, wrapper) {
        var selection = cm.getSelection();
        if (selection) {
            cm.replaceSelection(wrapper + selection + wrapper);
        } else {
            var cursor = cm.getCursor();
            cm.replaceRange(wrapper + wrapper, cursor);
            cm.setCursor({ line: cursor.line, ch: cursor.ch + wrapper.length });
        }
    }
    
    /**
     * Helper: Insert a markdown link
     */
    function insertLink(cm) {
        var selection = cm.getSelection();
        if (selection) {
            cm.replaceSelection('[' + selection + '](url)');
        } else {
            var cursor = cm.getCursor();
            cm.replaceRange('[text](url)', cursor);
            cm.setSelection(
                { line: cursor.line, ch: cursor.ch + 1 },
                { line: cursor.line, ch: cursor.ch + 5 }
            );
        }
    }
    
    // Public API
    return {
        init: init,
        openEditor: openEditor,
        getValue: getValue,
        setValue: setValue,
        switchEditorType: switchEditorType,
        refreshCurrentEditor: refreshCurrentEditor,
        getCurrentEditorType: function() { return currentEditorType; }
    };
})();

// Initialize when document is ready
$(document).ready(function() {
    MarkdownEditorManager.init();
});
