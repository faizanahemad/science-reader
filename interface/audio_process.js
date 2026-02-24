/**
 * VoiceTranscription - Modular voice recording and transcription class
 * Can be used with any textarea and voice button combination
 */
class VoiceTranscription {
    constructor(textareaSelector, buttonSelector, iconSelector) {
        this.mediaRecorder = null;
        this.audioChunks = [];
        this.isRecording = false;
        this.textareaSelector = textareaSelector;
        this.buttonSelector = buttonSelector;
        this.iconSelector = iconSelector;
        
        // Initialize when elements are available
        this.init();
    }
    
    init() {
        // Try to find elements and attach handlers
        this.attachHandlers();
    }
    
    attachHandlers() {
        const button = $(this.buttonSelector);
        const icon = $(this.iconSelector);
        const textarea = $(this.textareaSelector);
        
        if (button.length && icon.length && textarea.length) {
            // Remove any existing handlers to avoid duplicates
            button.off('click.voiceTranscription');
            
            // Attach click handler
            button.on('click.voiceTranscription', () => {
                this.toggleRecording();
            });
            
            console.log(`Voice transcription initialized for ${this.textareaSelector}`);
        }
    }
    
    toggleRecording() {
        if (!this.isRecording) {
            this.startRecording();
        } else {
            this.stopRecording();
        }
    }
    
    async startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            this.mediaRecorder = new MediaRecorder(stream);
            this.mediaRecorder.ondataavailable = (event) => {
                this.audioChunks.push(event.data);
            };
            this.mediaRecorder.onstop = () => this.sendAudioToServer();
            this.mediaRecorder.start();
            this.isRecording = true;
            this.animateRecordingStart();
        } catch (err) {
            console.error("Error accessing microphone:", err);
            
            let message = 'Failed to access microphone. ';
            if (err.name === 'NotAllowedError') {
                message += 'Click the camera/mic icon in the address bar and allow microphone access.';
            } else if (err.name === 'NotFoundError') {
                message += 'No microphone found. Please connect a microphone and try again.';
            } else if (err.name === 'NotReadableError') {
                message += 'Microphone is already in use by another application.';
            } else {
                message += 'Please check your browser and system permissions.';
            }
            
            this.showErrorMessage(message);
        }
    }
    
    stopRecording() {
        if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
            this.mediaRecorder.stop();
            this.isRecording = false;
            this.animateRecordingStop();
        }
    }
    
    sendAudioToServer() {
        const audioBlob = new Blob(this.audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        this.showLoadingIndicator();
        
        fetch('/transcribe', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            this.insertTranscribedText(data.transcription);
            this.hideLoadingIndicator();
        })
        .catch(error => {
            console.error('Error:', error);
            this.showErrorMessage("Failed to transcribe audio. Please try again.");
            this.hideLoadingIndicator();
        });
        this.audioChunks = [];
    }
    
    insertTranscribedText(text) {
        const textarea = $(this.textareaSelector);
        if (textarea.length) {
            const startPos = textarea[0].selectionStart;
            const endPos = textarea[0].selectionEnd;
            const currentValue = textarea.val();
            const beforeText = currentValue.substring(0, startPos);
            const afterText = currentValue.substring(endPos);
            
            textarea.val(beforeText + text + afterText);
            textarea[0].selectionStart = textarea[0].selectionEnd = startPos + text.length;
            textarea.focus();
        }
    }
    
    animateRecordingStart() {
        const icon = $(this.iconSelector);
        icon.removeClass('fa-microphone')
            .addClass('fa-stop')
            .css({
                'color': 'red',
                'animation': 'pulse 1s infinite'
            });
        
        // Add pulse animation if not already added
        if ($('#voice-pulse-animation').length === 0) {
            $('<style id="voice-pulse-animation">')
                .prop('type', 'text/css')
                .html(`  
                    @keyframes pulse {  
                        0% { transform: scale(1); opacity: 1; }  
                        50% { transform: scale(1.2); opacity: 0.7; }  
                        100% { transform: scale(1); opacity: 1; }  
                    }  
                `)
                .appendTo('head');
        }
    }
    
    animateRecordingStop() {
        const icon = $(this.iconSelector);
        icon.removeClass('fa-stop')
            .addClass('fa-microphone')
            .css({
                'color': '',
                'animation': ''
            });
    }
    
    showLoadingIndicator() {
        const icon = $(this.iconSelector);
        icon.addClass('fa-spin fa-spinner').removeClass('fa-microphone fa-stop');
    }
    
    hideLoadingIndicator() {
        const icon = $(this.iconSelector);
        icon.removeClass('fa-spin fa-spinner').addClass('fa-microphone');
    }
    
    showErrorMessage(message) {
        const textarea = $(this.textareaSelector);
        const errorDiv = $('<div>')
            .addClass('alert alert-danger mt-2')
            .text(message)
            .insertAfter(textarea);
        
        setTimeout(() => {
            errorDiv.fadeOut('slow', function () {
                $(this).remove();
            });
        }, 5000);
    }
    
    // Method to reinitialize when elements become available (for dynamic modals)
    reinitialize() {
        this.attachHandlers();
    }
}

// Global instances
let mainChatVoice = null;
let doubtChatVoice = null;

$(document).ready(function () {
    // Initialize main chat voice transcription
    mainChatVoice = new VoiceTranscription('#messageText', '#voice-record', 'label[for="voice-record"] i');
    
    // Global keyboard shortcut for voice transcription (Ctrl+K)
    // Skip when the file browser is open — Cmd+K is used there for AI Edit.
    $(document).on('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
            if ($('#file-browser-modal').hasClass('show')) return;
            event.preventDefault();
            if ($('#doubt-chat-modal').is(':visible') && doubtChatVoice) {
                doubtChatVoice.toggleRecording();
            } else if (mainChatVoice) {
                mainChatVoice.toggleRecording();
            }
        }
});  
