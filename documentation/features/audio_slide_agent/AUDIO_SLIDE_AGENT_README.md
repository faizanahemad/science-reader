# AudioSlideAgent - Audio-Enhanced Slide Presentations

## Overview

The AudioSlideAgent combines the power of slide generation with text-to-speech (TTS) capabilities to create multimedia presentations. Each slide gets its own audio narration with full playback controls, and the entire presentation can be exported as a video.

## Features

### 🎯 Core Features
- **Per-Slide Audio Generation**: Each slide gets its own synchronized audio narration
- **Multiple TTS Modes**: 
  - Standard TTS for general content
  - Code-focused TTS for technical content (explains concepts, not code verbatim)
  - Podcast-style dialogue between host and expert
- **Full Audio Controls**: Play/pause, rewind, progress bar, mute, speed control
- **Auto-Play Support**: Audio can auto-play when slides transition
- **Transcript Display**: Optional text display of audio content
- **Video Export**: Convert entire presentation to MP4 video
- **Presentation Mode**: Play entire slideshow with synchronized audio

### 🎨 Content Types
1. **Generic Content** (`AudioGenericSlideAgent`)
2. **Coding/Technical Content** (`AudioCodingSlideAgent`)
3. **Custom Content** (base `AudioSlideAgent`)

## Installation

```python
# Required dependencies
pip install pydub pillow ffmpeg-python

# For video export (system requirement)
# macOS: brew install ffmpeg
# Linux: sudo apt-get install ffmpeg
# Windows: Download from https://ffmpeg.org/
```

## Usage

### Basic Usage

```python
from agents.audio_slide_agent import AudioSlideAgent

# Initialize agent
agent = AudioSlideAgent(
    keys={'openAIKey': 'your-key', 'elevenLabsKey': 'optional-key'},
    writer_model="gpt-4o-mini",
    demo_mode=True,  # Standalone HTML
    tts_voice="nova",
    auto_play=True,
    show_controls=True
)

# Generate slides with audio
content = """
<main-content>
Your presentation content here...
</main-content>
"""

result = agent(content, generate_audio=True)
```

### Podcast Mode

```python
from agents.audio_slide_agent import AudioGenericSlideAgent

agent = AudioGenericSlideAgent(
    keys=keys,
    writer_model="gpt-4o-mini",
    enable_podcast_mode=True,
    host_voice="alloy",
    expert_voice="nova"
)

result = agent(content, use_podcast_mode=True)
```

### Coding Content with Specialized Audio

```python
from agents.audio_slide_agent import AudioCodingSlideAgent

agent = AudioCodingSlideAgent(
    keys=keys,
    writer_model="gpt-4o-mini",
    demo_mode=True
)

# The agent will explain algorithms and concepts, not read code verbatim
coding_content = """
<main-content>
Two Sum Problem
Given array nums and target, find two indices that sum to target.
Example: nums = [2,7,11,15], target = 9
Output: [0,1]
</main-content>
"""

result = agent(coding_content)
```

### Video Export

```python
# Generate presentation with video export
result = agent(
    content,
    generate_audio=True,
    export_video=True,
    video_output_path="presentation.mp4"
)

# Result contains:
# - html: Enhanced HTML with audio
# - slide_data: Structured slide information
# - audio_data: Audio file paths and transcripts
# - video_path: Path to exported video
```

## Configuration Options

### Agent Initialization Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `keys` | Dict | Required | API keys for LLM and TTS |
| `writer_model` | str/List | Required | Model(s) for content generation |
| `demo_mode` | bool | True | Standalone (True) or embedded (False) HTML |
| `content_mode` | str | None | 'generic', 'coding', or None |
| `tts_voice` | str | "nova" | TTS voice selection |
| `enable_podcast_mode` | bool | False | Enable dialogue-style audio |
| `host_voice` | str | "alloy" | Podcast host voice |
| `expert_voice` | str | "nova" | Podcast expert voice |
| `auto_play` | bool | True | Auto-play audio on slide show |
| `show_controls` | bool | True | Show audio control panel |
| `enable_transcript` | bool | False | Show/hide transcript option |
| `audio_speed` | float | 1.0 | Default playback speed |
| `pause_between_slides` | float | 1.0 | Pause duration (seconds) |

### Call Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | str | Required | Input content |
| `generate_audio` | bool | True | Generate audio for slides |
| `use_podcast_mode` | bool | None | Override podcast mode |
| `export_video` | bool | False | Export as video |
| `video_output_path` | str | None | Video file path |

## Audio Controls

Each slide includes an audio control panel with:
- ▶️ **Play/Pause**: Control audio playback
- ⏪ **Rewind**: Jump back 10 seconds
- **Progress Bar**: Seek to any position
- 🔊 **Mute/Unmute**: Toggle audio
- **Speed Control**: 0.5x to 2x playback speed
- 📝 **Transcript**: Show/hide text transcript

## Presentation Controls

Bottom control panel for full presentation:
- ▶️ **Play All**: Start presentation from beginning
- ⏸️ **Pause**: Pause presentation playback
- ⏹️ **Stop**: Stop and reset to first slide
- 🎥 **Export Video**: Generate MP4 video

## HTML Structure

The generated HTML includes:
1. **Reveal.js Integration**: Full slide functionality
2. **Embedded Audio**: Base64-encoded audio in HTML
3. **Custom Controls**: JavaScript-powered audio controls
4. **Responsive Design**: Works on desktop and mobile

## Video Export

Requirements:
- `ffmpeg` installed on system
- `PIL` (Pillow) for image generation
- `pydub` for audio processing

The video export:
1. Creates image frames for each slide
2. Combines audio tracks with pauses
3. Synchronizes slides with audio duration
4. Outputs MP4 with H.264 video and AAC audio

## Testing

Run the comprehensive test suite:

```bash
python test_audio_slide_agent.py
```

Tests include:
1. Basic audio slide generation
2. Podcast mode with dialogue
3. Coding content with specialized narration
4. Video export functionality
5. Audio control verification

## Architecture

```
AudioSlideAgent
├── SlideAgent (inherited)
│   ├── Slide generation
│   ├── HTML formatting
│   └── Storyboard creation
├── TTSAgent Integration
│   ├── Text-to-speech conversion
│   ├── Emotion handling
│   └── Voice selection
├── Audio Management
│   ├── Per-slide audio generation
│   ├── Audio file handling
│   └── Base64 encoding
├── Control System
│   ├── JavaScript controls
│   ├── Reveal.js integration
│   └── Presentation mode
└── Export System
    ├── Video generation
    ├── Frame creation
    └── Audio synchronization
```

## Browser Compatibility

- **Chrome**: ✅ Full support
- **Firefox**: ✅ Full support
- **Safari**: ✅ Full support
- **Edge**: ✅ Full support
- **Mobile Browsers**: ✅ With touch controls

## Troubleshooting

### Common Issues

1. **No Audio Generated**
   - Check API keys are valid
   - Ensure TTS service is accessible
   - Verify content is not empty

2. **Video Export Fails**
   - Install ffmpeg: `brew install ffmpeg` (macOS)
   - Check file permissions
   - Ensure sufficient disk space

3. **Controls Not Working**
   - Enable JavaScript in browser
   - Check browser console for errors
   - Try different browser

4. **Audio Out of Sync**
   - Adjust `pause_between_slides` parameter
   - Check audio file generation
   - Verify slide transition timing

## Future Enhancements

Potential improvements:
- [ ] Real-time streaming audio generation
- [ ] Multi-language support
- [ ] Custom voice cloning
- [ ] Background music support
- [ ] Animated slide transitions in video
- [ ] WebRTC for live presentations
- [ ] Collaborative editing
- [ ] Cloud storage integration

## License

This implementation is part of the chatgpt-iterative project and follows the project's licensing terms.

## Support

For issues or questions:
1. Check the test file for usage examples
2. Review the inline documentation
3. Examine the generated HTML for debugging
