"""
Audio Slide Agent - Combines SlideAgent with TTS capabilities for audio-enhanced presentations.

This agent creates slide presentations with synchronized audio narration for each slide,
including playback controls and video export capabilities.
"""

import os
import json
import tempfile
import shutil
import subprocess
import concurrent.futures
from typing import Dict, List, Optional, Union, Tuple, Generator
from pathlib import Path
import hashlib
import re
import time
import logging

# Import base agents
from .slide_agent import SlideAgent, GenericSlideAgent, CodingQuestionSlideAgent
from .tts_and_podcast_agent import TTSAgent, PodcastAgent, CodeTTSAgent

# Import utilities
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    
    from call_llm import CallLLm
    from common import CHEAP_LLM
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

# Configure logging
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    __name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO
)


class AudioSlideAgent(SlideAgent):
    """
    An enhanced slide agent that generates audio narration for each slide.
    
    This agent combines the slide generation capabilities of SlideAgent with
    TTS capabilities to create multimedia presentations with synchronized audio.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        writer_model: Union[List[str], str],
        demo_mode: bool = True,
        content_mode: Optional[str] = None,
        tts_voice: str = "nova",
        tts_model: str = "tts-1",
        enable_podcast_mode: bool = False,
        host_voice: str = "alloy",
        expert_voice: str = "nova",
        auto_play: bool = True,
        show_controls: bool = True,
        enable_transcript: bool = False,
        audio_speed: float = 1.0,
        pause_between_slides: float = 1.0,
        storage_path: Optional[str] = None
    ):
        """
        Initialize the AudioSlideAgent.
        
        Args:
            keys: API keys for LLM and TTS services
            writer_model: Model(s) to use for content generation
            demo_mode: If True, generates standalone HTML; if False, embedded HTML
            content_mode: Type of content (None, 'coding', 'generic')
            tts_voice: Voice to use for TTS
            tts_model: TTS model to use
            enable_podcast_mode: If True, use podcast-style dialogue for audio
            host_voice: Voice for podcast host
            expert_voice: Voice for podcast expert
            auto_play: If True, audio auto-plays when slide is shown
            show_controls: If True, show audio controls on each slide
            enable_transcript: If True, show transcript alongside audio
            audio_speed: Playback speed for audio (1.0 = normal)
            pause_between_slides: Pause duration between slides in seconds
            storage_path: Path to store generated audio files
        """
        # Initialize parent SlideAgent (without content_mode as it doesn't accept it)
        super().__init__(keys, writer_model, demo_mode)
        
        self.tts_voice = tts_voice
        self.tts_model = tts_model
        self.enable_podcast_mode = enable_podcast_mode
        self.host_voice = host_voice
        self.expert_voice = expert_voice
        self.auto_play = auto_play
        self.show_controls = show_controls
        self.enable_transcript = enable_transcript
        self.audio_speed = audio_speed
        self.pause_between_slides = pause_between_slides
        
        # Set up storage path for audio files
        if storage_path:
            self.storage_path = storage_path
        else:
            self.storage_path = tempfile.mkdtemp(prefix="audio_slides_")
        
        # Initialize TTS agents based on content mode
        if content_mode == 'coding':
            self.tts_agent = CodeTTSAgent(
                keys=keys,
                storage_path=self.storage_path,
                voice=tts_voice,
                model=tts_model,
                shortTTS=False
            )
        else:
            self.tts_agent = TTSAgent(
                keys=keys,
                storage_path=self.storage_path,
                voice=tts_voice,
                model=tts_model,
                shortTTS=False
            )
        
        # Initialize podcast agent if enabled
        if enable_podcast_mode:
            self.podcast_agent = PodcastAgent(
                keys=keys,
                storage_path=self.storage_path,
                host_voice=host_voice,
                expert_voice=expert_voice,
                shortTTS=False
            )
        else:
            self.podcast_agent = None
    
    def _generate_slide_audio(
        self,
        slide_content: str,
        slide_title: str,
        slide_number: int,
        total_slides: int,
        use_podcast: bool = False
    ) -> Tuple[str, str]:
        """
        Generate audio for a single slide.
        
        Args:
            slide_content: HTML content of the slide
            slide_title: Title of the slide
            slide_number: Current slide number
            total_slides: Total number of slides
            use_podcast: If True, use podcast-style narration
            
        Returns:
            Tuple of (audio_file_path, transcript_text)
        """
        # Extract text content from HTML for TTS
        text_content = self._extract_text_from_html(slide_content)
        
        # Add context for better narration
        narration_text = f"""
Slide {slide_number} of {total_slides}: {slide_title}

{text_content}
"""
        
        # Generate audio using appropriate agent
        audio_file = f"slide_{slide_number}_audio.mp3"
        audio_path = os.path.join(self.storage_path, audio_file)
        
        try:
            if use_podcast and self.podcast_agent:
                # Generate podcast-style audio
                self.podcast_agent.storage_path = audio_path
                self.podcast_agent(
                    narration_text,
                    topic=slide_title,
                    expert_name="Expert"
                )
            else:
                # Generate standard TTS audio
                self.tts_agent.storage_path = audio_path
                self.tts_agent(narration_text)
            
            success_logger.info(f"Generated audio for slide {slide_number}: {audio_path}")
            return audio_path, narration_text
            
        except Exception as e:
            error_logger.error(f"Error generating audio for slide {slide_number}: {e}")
            return None, narration_text
    
    def _extract_text_from_html(self, html_content: str) -> str:
        """
        Extract plain text from HTML content for TTS.
        
        Args:
            html_content: HTML content to extract text from
            
        Returns:
            Plain text suitable for TTS
        """
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', html_content)
        
        # Clean up code blocks
        text = re.sub(r'```[\s\S]*?```', '[Code block]', text)
        text = re.sub(r'`[^`]+`', '[inline code]', text)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()
        
        return text
    
    def _generate_audio_for_slides(
        self,
        slide_data: Dict,
        use_podcast: bool = None
    ) -> Dict[int, Tuple[str, str]]:
        """
        Generate audio for all slides in parallel.
        
        Args:
            slide_data: Dictionary containing slide information
            use_podcast: Override for podcast mode
            
        Returns:
            Dictionary mapping slide index to (audio_path, transcript) tuples
        """
        if use_podcast is None:
            use_podcast = self.enable_podcast_mode
        
        audio_data = {}
        slides = slide_data.get("slides", [])
        total_slides = len(slides)
        
        # Generate audio for each slide in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {}
            
            for i, slide in enumerate(slides):
                future = executor.submit(
                    self._generate_slide_audio,
                    slide.get("content", ""),
                    slide.get("title", f"Slide {i+1}"),
                    i + 1,
                    total_slides,
                    use_podcast
                )
                futures[future] = i
            
            # Collect results
            for future in concurrent.futures.as_completed(futures):
                slide_index = futures[future]
                try:
                    audio_path, transcript = future.result()
                    audio_data[slide_index] = (audio_path, transcript)
                except Exception as e:
                    error_logger.error(f"Error processing audio for slide {slide_index}: {e}")
                    audio_data[slide_index] = (None, "")
        
        return audio_data
    
    def _embed_audio_in_slides(
        self,
        slide_data: Dict,
        audio_data: Dict[int, Tuple[str, str]]
    ) -> Dict:
        """
        Embed audio controls and data into slide HTML.
        
        Args:
            slide_data: Original slide data
            audio_data: Dictionary mapping slide index to audio data
            
        Returns:
            Enhanced slide data with audio
        """
        enhanced_slides = []
        
        for i, slide in enumerate(slide_data.get("slides", [])):
            audio_path, transcript = audio_data.get(i, (None, ""))
            
            if audio_path and os.path.exists(audio_path):
                # Convert audio file to base64 for embedding
                audio_base64 = self._file_to_base64(audio_path)
                
                # Create audio control HTML
                audio_html = self._create_audio_control_html(
                    audio_base64,
                    transcript,
                    slide_index=i,
                    auto_play=self.auto_play and i == 0  # Auto-play first slide only
                )
                
                # Add audio controls to slide content
                enhanced_content = f"""
                {audio_html}
                <div class="slide-main-content">
                    {slide.get("content", "")}
                </div>
                """
                
                slide["content"] = enhanced_content
                slide["audio_path"] = audio_path
                slide["transcript"] = transcript
            
            enhanced_slides.append(slide)
        
        slide_data["slides"] = enhanced_slides
        slide_data["has_audio"] = True
        
        return slide_data
    
    def _file_to_base64(self, file_path: str) -> str:
        """
        Convert file to base64 string for embedding.
        
        Args:
            file_path: Path to file
            
        Returns:
            Base64 encoded string
        """
        import base64
        
        try:
            with open(file_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            error_logger.error(f"Error encoding file to base64: {e}")
            return ""
    
    def _create_audio_control_html(
        self,
        audio_base64: str,
        transcript: str,
        slide_index: int,
        auto_play: bool = False
    ) -> str:
        """
        Create HTML for audio controls on a slide.
        
        Args:
            audio_base64: Base64 encoded audio data
            transcript: Text transcript of audio
            slide_index: Index of the slide
            auto_play: Whether to auto-play audio
            
        Returns:
            HTML string for audio controls
        """
        audio_id = f"slide-audio-{slide_index}"
        transcript_id = f"transcript-{slide_index}"
        
        controls_html = f"""
        <div class="audio-controls" data-slide-index="{slide_index}">
            <audio id="{audio_id}" 
                   {'autoplay' if auto_play else ''} 
                   {'controls' if self.show_controls else ''}
                   preload="auto">
                <source src="data:audio/mp3;base64,{audio_base64}" type="audio/mp3">
                Your browser does not support the audio element.
            </audio>
            
            {f'''
            <div class="audio-custom-controls">
                <button class="audio-play-pause" data-audio-id="{audio_id}">
                    <span class="play-icon">▶️</span>
                    <span class="pause-icon" style="display:none;">⏸️</span>
                </button>
                <button class="audio-rewind" data-audio-id="{audio_id}">⏪</button>
                <input type="range" class="audio-progress" data-audio-id="{audio_id}" 
                       min="0" max="100" value="0">
                <span class="audio-time" data-audio-id="{audio_id}">0:00 / 0:00</span>
                <button class="audio-mute" data-audio-id="{audio_id}">🔊</button>
                <select class="audio-speed" data-audio-id="{audio_id}">
                    <option value="0.5">0.5x</option>
                    <option value="0.75">0.75x</option>
                    <option value="1" selected>1x</option>
                    <option value="1.25">1.25x</option>
                    <option value="1.5">1.5x</option>
                    <option value="2">2x</option>
                </select>
            </div>
            ''' if self.show_controls else ''}
            
            {f'''
            <div class="transcript-container" id="{transcript_id}" style="display:none;">
                <h4>Transcript</h4>
                <p class="transcript-text">{transcript}</p>
            </div>
            <button class="toggle-transcript" data-transcript-id="{transcript_id}">
                📝 Show Transcript
            </button>
            ''' if self.enable_transcript else ''}
        </div>
        """
        
        return controls_html
    
    def _generate_audio_enhanced_html(
        self,
        slide_data: Dict,
        audio_data: Dict[int, Tuple[str, str]]
    ) -> str:
        """
        Generate complete HTML with audio-enhanced slides.
        
        Args:
            slide_data: Slide data with embedded audio
            audio_data: Audio data for all slides
            
        Returns:
            Complete HTML string
        """
        # First embed audio in slides
        slide_data = self._embed_audio_in_slides(slide_data, audio_data)
        
        # Generate base HTML using parent class
        slides_html = self._generate_reveal_html(slide_data)
        
        # Add custom audio control scripts and styles
        audio_scripts = self._generate_audio_control_scripts()
        audio_styles = self._generate_audio_control_styles()
        
        # Inject audio scripts and styles into HTML
        if self.demo_mode:
            # For standalone HTML, inject into the complete document
            slides_html = slides_html.replace('</head>', f'{audio_styles}\n</head>')
            slides_html = slides_html.replace('</body>', f'{audio_scripts}\n</body>')
        else:
            # For embedded HTML, prepend styles and append scripts
            slides_html = f"{audio_styles}\n{slides_html}\n{audio_scripts}"
        
        return slides_html
    
    def _generate_audio_control_styles(self) -> str:
        """
        Generate CSS styles for audio controls.
        
        Returns:
            CSS style string
        """
        return """
        <style>
            .audio-controls {
                position: absolute;
                top: 10px;
                right: 10px;
                background: rgba(255, 255, 255, 0.95);
                padding: 10px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                z-index: 1000;
                max-width: 400px;
            }
            
            .audio-custom-controls {
                display: flex;
                align-items: center;
                gap: 10px;
                margin-top: 10px;
            }
            
            .audio-custom-controls button {
                background: #3498db;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
            }
            
            .audio-custom-controls button:hover {
                background: #2980b9;
            }
            
            .audio-progress {
                flex-grow: 1;
                height: 6px;
                cursor: pointer;
            }
            
            .audio-time {
                font-size: 12px;
                color: #666;
                white-space: nowrap;
            }
            
            .audio-speed {
                padding: 3px;
                border-radius: 4px;
                border: 1px solid #ddd;
                font-size: 12px;
            }
            
            .transcript-container {
                margin-top: 10px;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 4px;
                max-height: 150px;
                overflow-y: auto;
            }
            
            .transcript-text {
                font-size: 12px;
                line-height: 1.4;
                color: #333;
            }
            
            .toggle-transcript {
                margin-top: 5px;
                background: #6c757d;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                cursor: pointer;
                font-size: 12px;
            }
            
            .toggle-transcript:hover {
                background: #5a6268;
            }
            
            /* Presentation mode controls */
            .presentation-controls {
                position: fixed;
                bottom: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 15px;
                border-radius: 10px;
                display: flex;
                gap: 15px;
                z-index: 2000;
            }
            
            .presentation-controls button {
                background: #3498db;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                cursor: pointer;
                font-size: 14px;
            }
            
            .presentation-controls button:hover {
                background: #2980b9;
            }
            
            .presentation-progress {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 4px;
                background: rgba(0,0,0,0.2);
                z-index: 1999;
            }
            
            .presentation-progress-bar {
                height: 100%;
                background: #3498db;
                transition: width 0.3s ease;
            }
        </style>
        """
    
    def _generate_audio_control_scripts(self) -> str:
        """
        Generate JavaScript for audio control functionality.
        
        Returns:
            JavaScript code string
        """
        return """
        <script>
        (function() {
            // Audio control functionality
            class AudioSlideController {
                constructor() {
                    this.currentAudio = null;
                    this.isPlaying = false;
                    this.presentationMode = false;
                    this.init();
                }
                
                init() {
                    this.setupAudioControls();
                    this.setupSlideEvents();
                    this.setupPresentationControls();
                }
                
                setupAudioControls() {
                    // Play/Pause buttons
                    document.querySelectorAll('.audio-play-pause').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            const audioId = btn.dataset.audioId;
                            const audio = document.getElementById(audioId);
                            this.togglePlayPause(audio, btn);
                        });
                    });
                    
                    // Rewind buttons
                    document.querySelectorAll('.audio-rewind').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            const audioId = btn.dataset.audioId;
                            const audio = document.getElementById(audioId);
                            audio.currentTime = Math.max(0, audio.currentTime - 10);
                        });
                    });
                    
                    // Progress bars
                    document.querySelectorAll('.audio-progress').forEach(progress => {
                        const audioId = progress.dataset.audioId;
                        const audio = document.getElementById(audioId);
                        
                        audio.addEventListener('timeupdate', () => {
                            const percent = (audio.currentTime / audio.duration) * 100;
                            progress.value = percent || 0;
                            this.updateTimeDisplay(audio, audioId);
                        });
                        
                        progress.addEventListener('input', (e) => {
                            const percent = e.target.value;
                            audio.currentTime = (percent / 100) * audio.duration;
                        });
                    });
                    
                    // Mute buttons
                    document.querySelectorAll('.audio-mute').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            const audioId = btn.dataset.audioId;
                            const audio = document.getElementById(audioId);
                            audio.muted = !audio.muted;
                            btn.textContent = audio.muted ? '🔇' : '🔊';
                        });
                    });
                    
                    // Speed controls
                    document.querySelectorAll('.audio-speed').forEach(select => {
                        select.addEventListener('change', (e) => {
                            const audioId = select.dataset.audioId;
                            const audio = document.getElementById(audioId);
                            audio.playbackRate = parseFloat(e.target.value);
                        });
                    });
                    
                    // Transcript toggles
                    document.querySelectorAll('.toggle-transcript').forEach(btn => {
                        btn.addEventListener('click', (e) => {
                            const transcriptId = btn.dataset.transcriptId;
                            const transcript = document.getElementById(transcriptId);
                            if (transcript.style.display === 'none') {
                                transcript.style.display = 'block';
                                btn.textContent = '📝 Hide Transcript';
                            } else {
                                transcript.style.display = 'none';
                                btn.textContent = '📝 Show Transcript';
                            }
                        });
                    });
                }
                
                setupSlideEvents() {
                    // Listen for Reveal.js slide change events
                    if (typeof Reveal !== 'undefined') {
                        Reveal.on('slidechanged', (event) => {
                            this.onSlideChange(event.indexh);
                        });
                    }
                }
                
                setupPresentationControls() {
                    // Create presentation control panel
                    const controlPanel = document.createElement('div');
                    controlPanel.className = 'presentation-controls';
                    controlPanel.innerHTML = `
                        <button id="play-presentation">▶️ Play All</button>
                        <button id="pause-presentation" style="display:none;">⏸️ Pause</button>
                        <button id="stop-presentation">⏹️ Stop</button>
                        <button id="export-video">🎥 Export Video</button>
                    `;
                    document.body.appendChild(controlPanel);
                    
                    // Create progress bar
                    const progressBar = document.createElement('div');
                    progressBar.className = 'presentation-progress';
                    progressBar.innerHTML = '<div class="presentation-progress-bar"></div>';
                    document.body.appendChild(progressBar);
                    
                    // Add event listeners
                    document.getElementById('play-presentation').addEventListener('click', () => {
                        this.startPresentation();
                    });
                    
                    document.getElementById('pause-presentation').addEventListener('click', () => {
                        this.pausePresentation();
                    });
                    
                    document.getElementById('stop-presentation').addEventListener('click', () => {
                        this.stopPresentation();
                    });
                    
                    document.getElementById('export-video').addEventListener('click', () => {
                        this.exportVideo();
                    });
                }
                
                onSlideChange(slideIndex) {
                    // Stop current audio if playing
                    if (this.currentAudio) {
                        this.currentAudio.pause();
                        this.currentAudio.currentTime = 0;
                    }
                    
                    // Find and play audio for new slide
                    const slideAudio = document.querySelector(
                        `.audio-controls[data-slide-index="${slideIndex}"] audio`
                    );
                    
                    if (slideAudio && this.presentationMode) {
                        this.currentAudio = slideAudio;
                        slideAudio.play();
                        
                        // Auto-advance to next slide when audio ends
                        slideAudio.addEventListener('ended', () => {
                            if (this.presentationMode && typeof Reveal !== 'undefined') {
                                setTimeout(() => {
                                    Reveal.next();
                                }, """ + str(self.pause_between_slides * 1000) + """);
                            }
                        }, { once: true });
                    }
                }
                
                togglePlayPause(audio, button) {
                    if (audio.paused) {
                        audio.play();
                        button.querySelector('.play-icon').style.display = 'none';
                        button.querySelector('.pause-icon').style.display = 'inline';
                    } else {
                        audio.pause();
                        button.querySelector('.play-icon').style.display = 'inline';
                        button.querySelector('.pause-icon').style.display = 'none';
                    }
                }
                
                updateTimeDisplay(audio, audioId) {
                    const timeSpan = document.querySelector(`.audio-time[data-audio-id="${audioId}"]`);
                    if (timeSpan) {
                        const current = this.formatTime(audio.currentTime);
                        const duration = this.formatTime(audio.duration);
                        timeSpan.textContent = `${current} / ${duration}`;
                    }
                }
                
                formatTime(seconds) {
                    if (isNaN(seconds)) return '0:00';
                    const mins = Math.floor(seconds / 60);
                    const secs = Math.floor(seconds % 60);
                    return `${mins}:${secs.toString().padStart(2, '0')}`;
                }
                
                startPresentation() {
                    this.presentationMode = true;
                    document.getElementById('play-presentation').style.display = 'none';
                    document.getElementById('pause-presentation').style.display = 'inline';
                    
                    // Start from first slide
                    if (typeof Reveal !== 'undefined') {
                        Reveal.slide(0);
                    }
                }
                
                pausePresentation() {
                    this.presentationMode = false;
                    document.getElementById('play-presentation').style.display = 'inline';
                    document.getElementById('pause-presentation').style.display = 'none';
                    
                    if (this.currentAudio) {
                        this.currentAudio.pause();
                    }
                }
                
                stopPresentation() {
                    this.presentationMode = false;
                    document.getElementById('play-presentation').style.display = 'inline';
                    document.getElementById('pause-presentation').style.display = 'none';
                    
                    if (this.currentAudio) {
                        this.currentAudio.pause();
                        this.currentAudio.currentTime = 0;
                    }
                    
                    // Return to first slide
                    if (typeof Reveal !== 'undefined') {
                        Reveal.slide(0);
                    }
                }
                
                async exportVideo() {
                    alert('Video export will be processed server-side. This feature requires ffmpeg.');
                    // This would trigger a server-side process to combine slides and audio into video
                    // Implementation would depend on backend setup
                }
            }
            
            // Initialize controller when DOM is ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', () => {
                    new AudioSlideController();
                });
            } else {
                new AudioSlideController();
            }
        })();
        </script>
        """
    
    def export_to_video(
        self,
        slide_data: Dict,
        audio_data: Dict[int, Tuple[str, str]],
        output_path: str,
        fps: int = 1,
        resolution: str = "1920x1080"
    ) -> bool:
        """
        Export slides with audio to a video file using ffmpeg.
        
        Args:
            slide_data: Slide data dictionary
            audio_data: Audio data for slides
            output_path: Path for output video file
            fps: Frames per second for video
            resolution: Video resolution
            
        Returns:
            True if successful, False otherwise
        """
        try:
            import subprocess
            from PIL import Image, ImageDraw, ImageFont
            from pydub import AudioSegment
            
            # Create temporary directory for frames
            with tempfile.TemporaryDirectory() as temp_dir:
                frame_files = []
                audio_files = []
                
                # Generate image frames for each slide
                for i, slide in enumerate(slide_data.get("slides", [])):
                    # Create slide image (simplified - in production, use headless browser)
                    img_path = os.path.join(temp_dir, f"slide_{i:04d}.png")
                    self._create_slide_image(
                        slide.get("content", ""),
                        slide.get("title", ""),
                        img_path,
                        resolution
                    )
                    frame_files.append(img_path)
                    
                    # Get audio file
                    audio_path, _ = audio_data.get(i, (None, ""))
                    if audio_path and os.path.exists(audio_path):
                        audio_files.append(audio_path)
                
                # Combine audio files
                combined_audio_path = os.path.join(temp_dir, "combined_audio.mp3")
                self._combine_audio_files(audio_files, combined_audio_path, self.pause_between_slides)
                
                # Create video with ffmpeg
                frame_pattern = os.path.join(temp_dir, "slide_%04d.png")
                
                # Calculate duration for each slide based on audio
                durations = self._calculate_slide_durations(audio_files, self.pause_between_slides)
                
                # Create concat file for variable duration slides
                concat_file = os.path.join(temp_dir, "concat.txt")
                with open(concat_file, 'w') as f:
                    for i, (frame, duration) in enumerate(zip(frame_files, durations)):
                        f.write(f"file '{frame}'\n")
                        f.write(f"duration {duration}\n")
                
                # Run ffmpeg to create video
                cmd = [
                    'ffmpeg',
                    '-f', 'concat',
                    '-safe', '0',
                    '-i', concat_file,
                    '-i', combined_audio_path,
                    '-c:v', 'libx264',
                    '-c:a', 'aac',
                    '-pix_fmt', 'yuv420p',
                    '-shortest',
                    output_path
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    success_logger.info(f"Video exported successfully to {output_path}")
                    return True
                else:
                    error_logger.error(f"FFmpeg error: {result.stderr}")
                    return False
                    
        except Exception as e:
            error_logger.error(f"Error exporting video: {e}")
            return False
    
    def _create_slide_image(
        self,
        content: str,
        title: str,
        output_path: str,
        resolution: str
    ):
        """
        Create an image representation of a slide.
        
        Note: This is a simplified version. In production, consider using
        a headless browser to render actual HTML slides.
        """
        from PIL import Image, ImageDraw, ImageFont
        
        # Parse resolution
        width, height = map(int, resolution.split('x'))
        
        # Create image
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        # Try to use a nice font, fall back to default if not available
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 48)
            body_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 24)
        except:
            title_font = ImageFont.load_default()
            body_font = ImageFont.load_default()
        
        # Draw title
        draw.text((50, 50), title, fill='black', font=title_font)
        
        # Draw simplified content (just text for now)
        text_content = self._extract_text_from_html(content)
        lines = text_content.split('\n')
        y_offset = 150
        
        for line in lines[:20]:  # Limit lines to fit on slide
            draw.text((50, y_offset), line[:100], fill='black', font=body_font)
            y_offset += 30
        
        # Save image
        img.save(output_path)
    
    def _combine_audio_files(
        self,
        audio_files: List[str],
        output_path: str,
        pause_duration: float
    ):
        """
        Combine multiple audio files with pauses between them.
        """
        from pydub import AudioSegment
        
        combined = AudioSegment.empty()
        pause = AudioSegment.silent(duration=int(pause_duration * 1000))
        
        for audio_file in audio_files:
            if audio_file and os.path.exists(audio_file):
                audio = AudioSegment.from_mp3(audio_file)
                if len(combined) > 0:
                    combined += pause
                combined += audio
        
        combined.export(output_path, format="mp3")
    
    def _calculate_slide_durations(
        self,
        audio_files: List[str],
        pause_duration: float
    ) -> List[float]:
        """
        Calculate duration for each slide based on audio length.
        """
        from pydub import AudioSegment
        
        durations = []
        
        for audio_file in audio_files:
            if audio_file and os.path.exists(audio_file):
                audio = AudioSegment.from_mp3(audio_file)
                duration = len(audio) / 1000.0  # Convert to seconds
                durations.append(duration + pause_duration)
            else:
                durations.append(5.0)  # Default duration for slides without audio
        
        return durations
    
    def __call__(
        self,
        text: str,
        images: List = None,
        temperature: float = 0.7,
        stream: bool = False,
        max_tokens: Optional[int] = None,
        system: Optional[str] = None,
        web_search: bool = False,
        storyboard: List[tuple] = None,
        generate_audio: bool = True,
        use_podcast_mode: Optional[bool] = None,
        export_video: bool = False,
        video_output_path: Optional[str] = None
    ) -> Union[str, Dict]:
        """
        Generate audio-enhanced slides from input text.
        
        Args:
            text: Input text to convert to slides
            images: Optional images to include
            temperature: LLM temperature
            stream: Whether to stream output
            max_tokens: Maximum tokens for LLM
            system: System prompt override
            web_search: Enable web search
            storyboard: Pre-generated storyboard
            generate_audio: Whether to generate audio for slides
            use_podcast_mode: Override for podcast mode
            export_video: Whether to export as video
            video_output_path: Path for video export
            
        Returns:
            HTML string or dictionary with slide data and paths
        """
        # Generate slides using parent class
        slide_html = super().__call__(
            text, images, temperature, stream, max_tokens, system, web_search, storyboard
        )
        
        # Parse slide data from HTML if needed
        slide_data = self._parse_slide_data_from_html(slide_html)
        
        if generate_audio:
            # Generate audio for all slides
            audio_data = self._generate_audio_for_slides(
                slide_data,
                use_podcast_mode or self.enable_podcast_mode
            )
            
            # Create enhanced HTML with audio
            enhanced_html = self._generate_audio_enhanced_html(slide_data, audio_data)
            
            # Export to video if requested
            if export_video:
                if not video_output_path:
                    video_output_path = os.path.join(self.storage_path, "presentation.mp4")
                
                video_success = self.export_to_video(
                    slide_data,
                    audio_data,
                    video_output_path
                )
                
                return {
                    "html": enhanced_html,
                    "slide_data": slide_data,
                    "audio_data": audio_data,
                    "video_path": video_output_path if video_success else None,
                    "storage_path": self.storage_path
                }
            
            return enhanced_html
        else:
            return slide_html
    
    def _parse_slide_data_from_html(self, html: str) -> Dict:
        """
        Parse slide data from generated HTML.
        
        This is a simplified parser. In production, you might want to
        store slide data separately during generation.
        """
        # Extract slides from HTML
        slides = []
        
        # Simple regex to find slide sections
        import re
        slide_pattern = r'<section[^>]*>(.*?)</section>'
        matches = re.findall(slide_pattern, html, re.DOTALL)
        assert len(matches) > 0, "No slides found in HTML"
        
        for i, match in enumerate(matches):
            # Extract title (first h1, h2, or h3)
            title_match = re.search(r'<h[1-3][^>]*>(.*?)</h[1-3]>', match)
            title = title_match.group(1) if title_match else f"Slide {i+1}"
            
            slides.append({
                "title": title,
                "content": match,
                "transition": "slide"
            })
        
        return {
            "slides": slides,
            "metadata": {
                "total_slides": len(slides),
                "theme": "white"
            }
        }


class AudioGenericSlideAgent(AudioSlideAgent, GenericSlideAgent):
    """
    Audio-enhanced version of GenericSlideAgent.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        writer_model: Union[List[str], str],
        demo_mode: bool = True,
        **audio_kwargs
    ):
        """
        Initialize AudioGenericSlideAgent with both generic slide and audio capabilities.
        """
        # Initialize AudioSlideAgent (which will call GenericSlideAgent)
        super().__init__(
            keys=keys,
            writer_model=writer_model,
            demo_mode=demo_mode,
            **audio_kwargs
        )


class AudioCodingSlideAgent(AudioSlideAgent, CodingQuestionSlideAgent):
    """
    Audio-enhanced version of CodingQuestionSlideAgent.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        writer_model: Union[List[str], str],
        demo_mode: bool = True,
        **audio_kwargs
    ):
        """
        Initialize AudioCodingSlideAgent with both coding slide and audio capabilities.
        """
        # Initialize AudioSlideAgent (which will call CodingQuestionSlideAgent)
        super().__init__(
            keys=keys,
            writer_model=writer_model,
            demo_mode=demo_mode,
            **audio_kwargs
        )
