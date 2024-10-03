$(document).ready(function () {
    let mediaRecorder;
    let audioChunks = [];
    let isRecording = false;
    const voiceRecordButton = $('#voice-record');
    const voiceRecordIcon = $('label[for="voice-record"] i');
    const messageTextarea = $('#messageText');

    function toggleRecording() {
        if (!isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    }

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.ondataavailable = (event) => {
                audioChunks.push(event.data);
            };
            mediaRecorder.onstop = sendAudioToServer;
            mediaRecorder.start();
            isRecording = true;
            animateRecordingStart();
        } catch (err) {
            console.error("Error accessing microphone:", err);
            showErrorMessage("Failed to access microphone. Please check your permissions and try again.");
        }
    }

    function stopRecording() {
        if (mediaRecorder && mediaRecorder.state !== 'inactive') {
            mediaRecorder.stop();
            isRecording = false;
            animateRecordingStop();
        }
    }

    function sendAudioToServer() {
        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', audioBlob, 'recording.webm');
        showLoadingIndicator();
        fetch('/transcribe', {
            method: 'POST',
            body: formData
        })
            .then(response => response.json())
            .then(data => {
                insertTranscribedText(data.transcription);
                hideLoadingIndicator();
            })
            .catch(error => {
                console.error('Error:', error);
                showErrorMessage("Failed to transcribe audio. Please try again.");
                hideLoadingIndicator();
            });
        audioChunks = [];
    }

    function insertTranscribedText(text) {
        const startPos = messageTextarea[0].selectionStart;
        const endPos = messageTextarea[0].selectionEnd;
        const currentValue = messageTextarea.val();
        const beforeText = currentValue.substring(0, startPos);
        const afterText = currentValue.substring(endPos);

        messageTextarea.val(beforeText + text + afterText);
        messageTextarea[0].selectionStart = messageTextarea[0].selectionEnd = startPos + text.length;
        messageTextarea.focus();
    }

    function animateRecordingStart() {
        voiceRecordIcon
            .removeClass('fa-microphone')
            .addClass('fa-stop')
            .css({
                'color': 'red',
                'animation': 'pulse 1s infinite'
            });

        $('<style>')
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

    function animateRecordingStop() {
        voiceRecordIcon
            .removeClass('fa-stop')
            .addClass('fa-microphone')
            .css({
                'color': '',
                'animation': ''
            });
    }

    function showLoadingIndicator() {
        voiceRecordIcon.addClass('fa-spin fa-spinner').removeClass('fa-microphone fa-stop');
    }

    function hideLoadingIndicator() {
        voiceRecordIcon.removeClass('fa-spin fa-spinner').addClass('fa-microphone');
    }

    function showErrorMessage(message) {
        const errorDiv = $('<div>')
            .addClass('alert alert-danger mt-2')
            .text(message)
            .insertAfter(messageTextarea);

        setTimeout(() => {
            errorDiv.fadeOut('slow', function () {
                $(this).remove();
            });
        }, 5000);
    }

    voiceRecordButton.on('click', toggleRecording);

    $(document).on('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key === 'k') {
            event.preventDefault();
            toggleRecording();
        }
    });
});  
