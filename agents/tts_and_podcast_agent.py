import random  
from typing import Union, List, Dict, Tuple, Generator, Optional, Any, Set  
import uuid  
import os  
import tempfile  
import shutil  
import concurrent.futures  
import logging  
import time  
import json  
import hashlib  
import re  
import io  
from pathlib import Path  
from functools import lru_cache  
from dataclasses import dataclass, field  
import warnings
# Suppress specific warning
warnings.filterwarnings("ignore", message=".*DeprecationWarning: Due to a bug, this method doesn't actually stream the response content, `.with_streaming_response.method()` should be used instead.*")
# Suppress all warnings
warnings.filterwarnings("ignore")

  
# Third-party imports  
from pydub import AudioSegment  
from pydub.effects import speedup, normalize  
from pydub.generators import Sine  
  
# Local imports  
try:
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).parent.parent))
    
    from call_llm import CallLLm
    from common import (
        CHEAP_LLM, USE_OPENAI_API
    )
    from loggers import getLoggers
except ImportError as e:
    print(f"Import error: {e}")
    raise

from .base_agent import Agent

  
# Configure logging  
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(  
    __name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO  
)  
  
# Import the required TTS clients based on configuration  
if USE_OPENAI_API:  
    from openai import OpenAI  
else:  
    from elevenlabs.client import ElevenLabs  
  
# Update TTS friendly format instructions to include new emotion tagging  
tts_friendly_format_instructions = """  
**TTS Guidelines for TTS friendly format**:  
  - For converting given text to TTS format you only need to reformat the text as given below (if we are using shortTTS, then follow the shortTTS instructions below and provide a modified shorter response), do not add any new content or information.  
  - You can remove content or information and reduce or shorten the response if we are using shortTTS.  
  - Insert **two newlines** between major content sections to create natural pauses in speech.  
  - **Avoid code snippets and complex tables** that are not conducive to audio understanding. Code snippets should be summarized in text form in a simple and concise manner in spoken form. Comparisons and tables should be summarized in text form.  
  - If you need to write math or equations, then write very simple math or equations using text which can be read out by TTS.  
  - Write the answer in a way that it is TTS friendly without missing any details, has pauses, utilises emotions, sounds natural, uses enumerated counted points and repetitions to help understanding while listening.  
  - Provide visual cues and imagination cues to help the listener understand the text better.  
  - For pauses use `*pause*` and `*short pause*`, while for changing voice tones use `[speaking thoughtfully]` , `[positive tone]` , `[cautious tone]`, `[serious tone]`, `[speaking with emphasis]`, `[speaking warmly]`, `[speaking with authority]`, `[speaking encouragingly]`,  etc, notice that the tones use square brackets and can only have 2 words, and looks as `speaking …`.  
  - You can also use emotion tags at the beginning of paragraphs or sentences to indicate emotion changes. Place the emotion tag on its own line before the text like this:  
    <emotion>excited</emotion>  
    This is some excited text that will be spoken with enthusiasm!  
  - NOTE: Bracket-based emotions (`[speaking thoughtfully]`) will be kept in the text and processed by the TTS engine directly. Tag-based emotions (`<emotion>excited</emotion>`) will only apply to the next paragraph and will be removed during processing.  
  - Use both bracket-based and tag-based emotions to make the text more engaging and interesting. Use the tag-based emotions to indicate the emotion of the next paragraph of text. Use the bracket-based emotions to indicate the emotion of the current paragraph of text. Use them in abundance.
  - Available emotions include: neutral, excited, serious, curious, thoughtful, enthusiastic, cautious, surprised, happy, sad, angry, authoritative, humorous, wistful, optimistic, pensive, anxious, whisper, loud, shouting, soft, dramatic, mysterious, urgent, calm, and more.  
  - For enumerations use `Firstly,`, `Secondly,`, `Thirdly,` etc. For repetitions use `repeating`, `repeating again`, `repeating once more` etc. Write in a good hierarchy and structure.  
  - Write one sentence per line. If sentences are very short, then write multiple sentences in a single line.
  - Before each line write the emotion square brackets like this: `[speaking excitedly]` or `[speaking calmly]` or `[speaking optimistically]` etc as mentioned above.
  - Put new paragraphs in double new lines (2 or more newlines) and separate different topics and information into different paragraphs.  
  - If you are writing code, then write pseudocode or very small python code snippets which are less than 4096 characters.  
  - Ensure that each individual semantic chunk of text is small and less than 4096 characters.  
  - If the question is a leetcode or coding interview question, then explain the question and then the solution in a step by step manner with details and verbalised psedocode. Focus on question and solution mainly.
  - For coding questions, mention the examples in a visualised way and explain the algorithm in a top down speaking manner. Then explain the pseudocode or solution in a step by step manner.
"""  


stts_prompt = """  
Further TTS Formatting Instructions (shortTTS = True or shortTTS instructions are enabled):  
- Our reader is a busy person and has limited time to read. We need to shorten the text and give a concise response.  
- Summarize the text to keep it concise, use TTS friendly format.  
- Omit extraneous details while maintaining coherence and continuity in the flow.  
- Keep sentences short for easier spoken delivery.  
- Give a very short response while adhering to the TTS friendly format.  
- Preserve essential context so the meaning remains clear.  
- Make it shorter, brief and concise. 
- If the question is a leetcode or coding interview question, then explain the question and then the solution in a step by step manner with details and verbalised psedocode. Focus on question and solution mainly.
- No recaps and no summaries. 
- For coding questions, mention the examples in a visualised way and explain the algorithm in a top down speaking manner. Then explain the pseudocode or solution in a step by step manner.
"""

stts_podcast_prompt = stts_prompt + """  
Further Podcast Formatting Instructions (shortTTS = True):  
- Our podcast is concise and to the point.  
- Keep the dialogue natural but brief.  
- Focus on the most important points while maintaining an engaging conversation.  
- Use short sentences and clear transitions between speakers.  
- Make it sound like a real conversation but keep it brief.  
- Get straight to the point and don't waste time on introductions or background information.

"""
  
# Define podcast templates  
@dataclass  
class PodcastTemplate:  
    """Template for podcast format with specific structure and speaker roles."""  
    name: str  
    description: str  
    structure: List[str]  
    host_role: str  
    expert_role: str  
    intro_template: str  
    outro_template: str  
    transition_phrases: List[str] = field(default_factory=list)  
    sound_effect_points: List[str] = field(default_factory=list)  
  

# Sound effects library  
SOUND_EFFECTS = {  
    "intro": "intro_jingle.mp3",  
    "outro": "outro_jingle.mp3",  
    "transition": "transition_sound.mp3",  
    "key_concept": "lightbulb_moment.mp3",  
    "misconception": "correction_sound.mp3",  
    "perspective_shift": "perspective_shift.mp3",  
    "agreement": "agreement_chime.mp3",  
    "challenge": "dramatic_chord.mp3",  
    "turning_point": "turning_point.mp3",  
    "resolution": "resolution_sound.mp3",  
    "applause": "applause.mp3",  
    "surprise": "surprise_sound.mp3",  
    "question": "question_sound.mp3",  
    "success": "success_sound.mp3"  
}  
  
# Enhanced Voice emotion mappings with more aggressive parameters  
VOICE_EMOTIONS = {  
    # Basic emotions  
    "neutral": {  
        "openai": {"speed": 1.0, "volume": 0},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.5, "style": 0.0, "use_speaker_boost": True}  
    },  
    "excited": {  
        "openai": {"speed": 1.2, "volume": 6},  
        "elevenlabs": {"stability": 0.3, "similarity_boost": 0.7, "style": 0.7, "use_speaker_boost": True}  
    },  
    "serious": {  
        "openai": {"speed": 0.85, "volume": -2},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.3, "style": 0.3, "use_speaker_boost": True}  
    },  
    "curious": {  
        "openai": {"speed": 1.05, "volume": 2},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.4, "use_speaker_boost": True}  
    },  
    "thoughtful": {  
        "openai": {"speed": 0.9, "volume": -1},  
        "elevenlabs": {"stability": 0.7, "similarity_boost": 0.4, "style": 0.3, "use_speaker_boost": True}  
    },  
      
    # Volume-focused emotions  
    "whisper": {  
        "openai": {"speed": 0.8, "volume": -10},  
        "elevenlabs": {"stability": 0.9, "similarity_boost": 0.2, "style": 0.1, "use_speaker_boost": False}  
    },  
    "loud": {  
        "openai": {"speed": 1.1, "volume": 8},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.7, "style": 0.6, "use_speaker_boost": True}  
    },  
    "shouting": {  
        "openai": {"speed": 1.2, "volume": 12},  
        "elevenlabs": {"stability": 0.3, "similarity_boost": 0.8, "style": 0.8, "use_speaker_boost": True}  
    },  
    "soft": {  
        "openai": {"speed": 0.9, "volume": -6},  
        "elevenlabs": {"stability": 0.7, "similarity_boost": 0.3, "style": 0.2, "use_speaker_boost": False}  
    },  
      
    # Speed-focused emotions  
    "rapid": {  
        "openai": {"speed": 1.3, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "slow": {  
        "openai": {"speed": 0.7, "volume": -2},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.3, "style": 0.2, "use_speaker_boost": True}  
    },  
    "very_slow": {  
        "openai": {"speed": 0.6, "volume": -3},  
        "elevenlabs": {"stability": 0.9, "similarity_boost": 0.2, "style": 0.1, "use_speaker_boost": True}  
    },  
      
    # Complex emotional states  
    "enthusiastic": {  
        "openai": {"speed": 1.2, "volume": 7},  
        "elevenlabs": {"stability": 0.3, "similarity_boost": 0.8, "style": 0.7, "use_speaker_boost": True}  
    },  
    "cautious": {  
        "openai": {"speed": 0.85, "volume": -3},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.2, "style": 0.2, "use_speaker_boost": True}  
    },  
    "surprised": {  
        "openai": {"speed": 1.15, "volume": 5},  
        "elevenlabs": {"stability": 0.2, "similarity_boost": 0.9, "style": 0.6, "use_speaker_boost": True}  
    },  
    "happy": {  
        "openai": {"speed": 1.15, "volume": 4},  
        "elevenlabs": {"stability": 0.3, "similarity_boost": 0.7, "style": 0.6, "use_speaker_boost": True}  
    },  
    "sad": {  
        "openai": {"speed": 0.8, "volume": -4},  
        "elevenlabs": {"stability": 0.9, "similarity_boost": 0.2, "style": 0.3, "use_speaker_boost": False}  
    },  
    "angry": {  
        "openai": {"speed": 1.1, "volume": 8},  
        "elevenlabs": {"stability": 0.6, "similarity_boost": 0.4, "style": 0.7, "use_speaker_boost": True}  
    },  
    "authoritative": {  
        "openai": {"speed": 0.95, "volume": 3},  
        "elevenlabs": {"stability": 0.6, "similarity_boost": 0.4, "style": 0.5, "use_speaker_boost": True}  
    },  
      
    # Stylistic emotions  
    "humorous": {  
        "openai": {"speed": 1.1, "volume": 2},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.6, "style": 0.6, "use_speaker_boost": True}  
    },  
    "wistful": {  
        "openai": {"speed": 0.85, "volume": -2},  
        "elevenlabs": {"stability": 0.7, "similarity_boost": 0.4, "style": 0.4, "use_speaker_boost": False}  
    },  
    "optimistic": {  
        "openai": {"speed": 1.05, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "pensive": {  
        "openai": {"speed": 0.85, "volume": -3},  
        "elevenlabs": {"stability": 0.7, "similarity_boost": 0.3, "style": 0.3, "use_speaker_boost": False}  
    },  
    "anxious": {  
        "openai": {"speed": 1.15, "volume": 1},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.5, "style": 0.4, "use_speaker_boost": True}  
    },  
      
    # Dramatic emotions  
    "dramatic": {  
        "openai": {"speed": 0.9, "volume": 5},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.6, "style": 0.7, "use_speaker_boost": True}  
    },  
    "mysterious": {  
        "openai": {"speed": 0.85, "volume": -2},  
        "elevenlabs": {"stability": 0.6, "similarity_boost": 0.5, "style": 0.5, "use_speaker_boost": False}  
    },  
    "urgent": {  
        "openai": {"speed": 1.2, "volume": 6},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.7, "style": 0.6, "use_speaker_boost": True}  
    },  
    "calm": {  
        "openai": {"speed": 0.9, "volume": -3},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.3, "style": 0.2, "use_speaker_boost": False}  
    },  
      
    # Variations for compatibility with different formats  
    "speaking_thoughtfully": {  
        "openai": {"speed": 0.9, "volume": -1},  
        "elevenlabs": {"stability": 0.7, "similarity_boost": 0.4, "style": 0.3, "use_speaker_boost": True}  
    },  
    "positive_tone": {  
        "openai": {"speed": 1.05, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "cautious_tone": {  
        "openai": {"speed": 0.85, "volume": -3},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.2, "style": 0.2, "use_speaker_boost": True}  
    },  
    "serious_tone": {  
        "openai": {"speed": 0.85, "volume": -2},  
        "elevenlabs": {"stability": 0.8, "similarity_boost": 0.3, "style": 0.3, "use_speaker_boost": True}  
    },  
    "speaking_with_emphasis": {  
        "openai": {"speed": 0.95, "volume": 5},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.6, "style": 0.6, "use_speaker_boost": True}  
    },  
    "speaking_warmly": {  
        "openai": {"speed": 0.95, "volume": 2},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.6, "style": 0.4, "use_speaker_boost": True}  
    },  
    "speaking_with_warmth": {
        "openai": {"speed": 0.95, "volume": 2},  
        "elevenlabs": {"stability": 0.5, "similarity_boost": 0.6, "style": 0.4, "use_speaker_boost": True}  
    },  
    "speaking_with_authority": {  
        "openai": {"speed": 0.95, "volume": 3},  
        "elevenlabs": {"stability": 0.6, "similarity_boost": 0.4, "style": 0.5, "use_speaker_boost": True}  
    }, 
    "speaking_authoritatively": {
        "openai": {"speed": 0.95, "volume": 3},  
        "elevenlabs": {"stability": 0.6, "similarity_boost": 0.4, "style": 0.5, "use_speaker_boost": True}  
    },  
    "speaking_encouragingly": {  
        "openai": {"speed": 1.05, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "speaking_optimistically": {
        "openai": {"speed": 0.95, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "speaking_with_optimism": {
        "openai": {"speed": 0.95, "volume": 3},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "speaking_excitedly": {
        "openai": {"speed": 1.15, "volume": 4},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    }, 
    "speaking_with_excitement": {
        "openai": {"speed": 1.15, "volume": 4},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
    "speaking_enthusiastically": {
        "openai": {"speed": 1.15, "volume": 4},  
        "elevenlabs": {"stability": 0.4, "similarity_boost": 0.6, "style": 0.5, "use_speaker_boost": True}  
    },  
}  
  
# Add aliases for each emotion to handle variations  
EMOTION_ALIASES = {  
    # Map bracket format to emotion names  
    "speaking thoughtfully": "thoughtful",  
    "positive tone": "happy",  
    "cautious tone": "cautious",  
    "serious tone": "serious",  
    "speaking with emphasis": "authoritative",  
    "speaking warmly": "optimistic",  
    "speaking with authority": "authoritative",  
    "speaking encouragingly": "enthusiastic",  
    "speaking excitedly": "excited",  
    "speaking with excitement": "excited",  
    "speaking with optimism": "optimistic",  
    "speaking with enthusiasm": "enthusiastic",  
    "speaking with warmth": "optimistic",  
    "speaking enthusiastically": "enthusiastic",  
    "speaking authoritatively": "authoritative",  
      
    
      
    # Common variations  
    "excited voice": "excited",  
    "serious voice": "serious",  
    "curious voice": "curious",  
    "thoughtful voice": "thoughtful",  
    "enthusiastic voice": "enthusiastic",  
    "cautious voice": "cautious",  
    "surprised voice": "surprised",  
    "happy voice": "happy",  
    "sad voice": "sad",  
    "angry voice": "angry",  
    "authoritative voice": "authoritative",  
    "humorous voice": "humorous",  
    "wistful voice": "wistful",  
    "optimistic voice": "optimistic",  
    "pensive voice": "pensive",  
    "anxious voice": "anxious",  
    "dramatic voice": "dramatic",  
    "mysterious voice": "mysterious",  
    "urgent voice": "urgent",  
    "calm voice": "calm",  
    "whisper voice": "whisper",  
    "loud voice": "loud",  
    "shouting voice": "shouting",  
    "soft voice": "soft",  
    "rapid voice": "rapid",  
    "slow voice": "slow",  
    "very slow voice": "very_slow",  
}  

# Verify all emotions in the prompt are in VOICE_EMOTIONS  
emotion_list = [  
    "neutral", "excited", "serious", "curious", "thoughtful",   
    "enthusiastic", "cautious", "surprised", "happy", "sad",   
    "angry", "authoritative", "humorous", "wistful", "optimistic",   
    "pensive", "anxious", "whisper", "loud", "shouting",   
    "soft", "dramatic", "mysterious", "urgent", "calm"  
]  
  
for emotion in emotion_list:  
    if emotion not in VOICE_EMOTIONS:  
        print(f"Missing emotion: {emotion}")  

  
class TTSAgent(Agent):  
    """Base TTS Agent that converts text to speech."""  
  
    def __init__(  
        self,  
        keys: Dict[str, str],  
        storage_path: str,  
        convert_to_tts_friendly_format: bool = True,  
        shortTTS: bool = False,  
        voice: str = "nova",  
        model: str = "tts-1",  
        audio_format: str = "mp3",  
        max_workers: int = None,  
    ):  
        """  
        Initialize the TTSAgent.  
  
        Args:  
            keys: API keys for LLM and TTS services  
            storage_path: Path to store the generated audio files  
            convert_to_tts_friendly_format: Whether to convert text to TTS-friendly format  
            shortTTS: Whether to generate shorter TTS content  
            voice: Default voice to use  
            model: TTS model to use  
            audio_format: Output audio format  
            max_workers: Maximum number of parallel workers  
        """  
        self.keys = keys  
        self.storage_path = storage_path  
        if not os.path.exists(storage_path) and not storage_path.endswith('.mp3'):  
            os.makedirs(storage_path, exist_ok=True)  
  
        self.convert_to_tts_friendly_format = convert_to_tts_friendly_format  
        self.shortTTS = shortTTS  
        self.voice = voice  
        self.model = model  
        self.audio_format = audio_format  
        self.max_workers = max_workers or min(32, os.cpu_count() + 4)  
  
        # Initialize TTS client  
        if USE_OPENAI_API:  
            self.client = OpenAI(api_key=os.environ.get("openAIKey", keys["openAIKey"]))  
            self.provider = "openai"  
        else:  
            self.client = ElevenLabs(api_key=os.environ.get("elevenLabsKey", keys["elevenLabsKey"]))  
            self.provider = "elevenlabs"  
  
        # Set up prompts  
        shortTTS_prompt = stts_prompt if self.shortTTS else ""  
  
        self.system = f"""  
You are an expert TTS (Text To Speech) agent.  
You will be given a text and you need to convert it into a TTS friendly format.  
You need to convert the given text into a TTS friendly format using the following TTS Guidelines:  
{tts_friendly_format_instructions}  
{shortTTS_prompt}  
Ensure that you only convert the text and do not add any new content or information.  
"""  
        self.prompt = self.system + f"""  
Original answer or text to convert to TTS friendly format:  
<|context|>  
{{text}}  
</|context|>\n\n  
{shortTTS_prompt}  
Write the original answer or text in a TTS friendly format using the above TTS Guidelines:  
"""  
  
    def is_tts_friendly(self, text: str) -> bool:  
        """  
        Check if the text is already in TTS-friendly format.  
  
        Args:  
            text: The text to check  
  
        Returns:  
            bool: True if text appears to be TTS-friendly, False otherwise  
        """  
        # Check for pause markers  
        pause_pattern = r'\*(?:pause|short pause)\*'  
  
        # Check for tone indicators - matches [speaking ...] or [positive tone] etc.  
        tone_pattern = r'\\\[(speaking|positive|cautious|serious)(?:\s+\w+)?\\\]'  
  
        # Check for emotion tags  
        emotion_tag_pattern = r'<emotion>(\w+)</emotion>'  
  
        # Check for enumeration markers  
        enumeration_pattern = r'(?:Firstly|Secondly|Thirdly)'  
  
        # Check format markers  
        has_markers = bool(re.search(pause_pattern, text, re.IGNORECASE) or  
                        re.search(tone_pattern, text, re.IGNORECASE) or  
                        re.search(emotion_tag_pattern, text, re.IGNORECASE) or  
                        re.search(enumeration_pattern, text))  
  
        # Check chunk sizes  
        chunks = text.split('\n\n')  
        MAX_CHUNK_SIZE = 4000  
        chunks_within_limit = all(len(chunk.strip()) <= MAX_CHUNK_SIZE for chunk in chunks)  
  
        return has_markers and chunks_within_limit  
  
    def make_tts_friendly(self, text: str, force_tts_friendly: bool = False, **kwargs) -> str:  
        """  
        Convert text to TTS friendly format if needed.  
  
        Args:  
            text: Text to convert  
            **kwargs: Additional arguments for the LLM call  
  
        Returns:  
            str: TTS-friendly text  
        """  
        if (self.convert_to_tts_friendly_format and not self.is_tts_friendly(text)) or force_tts_friendly:  
            try:  
                llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])  
                return llm(self.prompt.format(text=text), **kwargs)  
            except Exception as e:  
                error_logger.error(f"Error converting to TTS friendly format: {e}")  
                return text  # Return original text if conversion fails  
        else:  
            return text  
  
    def __call__(self, text: str, **kwargs) -> str:  
        """  
        Convert text to speech and return the path to the audio file.  
  
        Args:  
            text: Text to convert to speech  
            **kwargs: Additional arguments  
  
        Returns:  
            str: Path to the generated audio file  
        """  
        # Convert to TTS friendly format if needed  
        tts_text_v1 = self.make_tts_friendly(text, **kwargs)  
        tts_text_v1 = tts_text_v1.replace("</emotion>\n\n", "</emotion>\n")
        print(tts_text_v1)  
        text = tts_text_v1
        
        # new_text = f"Original text: '''\n{text}\n'''\n\nTTS text: '''\n{tts_text_v1}\n'''\n\nNote that the TTS text can use square bracket emotions and emotions tags more and better, also each emotion tag should be used in a new paragraph, not in the middle of a paragraph. And each emotion tag should be followed by a new line and the corresponding emotion square bracket."
        # text = self.make_tts_friendly(new_text, force_tts_friendly=True, **kwargs)
        # text = text.replace("</emotion>\n\n", "</emotion>\n")
        # print(text)
  
        # Create temporary directory  
        with tempfile.TemporaryDirectory() as temp_dir:  
            # Parse text for emotion tags and split into segments  
            segments = self._parse_text_with_emotions(text)  
            chunk_files = []  
  
            # Process segments in parallel  
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:  
                futures = []  
  
                # Submit tasks for each segment  
                for i, (segment_text, emotion) in enumerate(segments):  
                    if segment_text.strip():  # Skip empty segments  
                        temp_file = os.path.join(temp_dir, f'chunk_{i}.mp3')  
  
                        # Get previous and next segments for context  
                        previous_text = segments[i-1][0].strip() if i > 0 else ""  
                        next_text = segments[i+1][0].strip() if i < len(segments)-1 else ""  
  
                        futures.append(  
                            executor.submit(  
                                self._generate_audio_chunk,  
                                segment_text.strip(),  
                                temp_file,  
                                previous_text,  
                                next_text,  
                                self.voice,  
                                emotion  
                            )  
                        )  
  
                # Collect results  
                for future in futures:  
                    try:  
                        chunk_file = future.result()  
                        if chunk_file:  
                            chunk_files.append(chunk_file)  
                    except Exception as e:  
                        error_logger.error(f"Error processing audio chunk: {e}")  
  
            # Determine final output path  
            if self.storage_path.endswith('.mp3'):  
                output_path = self.storage_path  
            else:  
                os.makedirs(self.storage_path, exist_ok=True)  
                output_path = os.path.join(self.storage_path, 'output.mp3')  
  
            # Merge audio files if there are multiple chunks  
            if len(chunk_files) > 1:  
                self._merge_audio_files(chunk_files, output_path)  
            elif len(chunk_files) == 1:  
                shutil.copy2(chunk_files[0], output_path)  
            else:  
                # No audio generated  
                error_logger.error("No audio chunks were successfully generated")  
                # Create an empty audio file  
                silent = AudioSegment.silent(duration=1000)  
                silent.export(output_path, format="mp3")  
  
        return output_path  
  
    def _parse_text_with_emotions(self, text: str) -> List[Tuple[str, str]]:  
        """  
        Parse text for emotion tags and split into segments with associated emotions.  
        
        Handles two types of emotions:  
        1. Tag-based emotions (<emotion>excited</emotion>) - Apply to all lines until next empty line or emotion tag  
        2. Square bracket emotions ([speaking thoughtfully]) - Apply only to current line, override tag emotion  
        
        Args:  
            text: Text to parse  
            
        Returns:  
            List[Tuple[str, str]]: List of (text, emotion) tuples  
        """  
        segments = []  
        paragraph_emotion = "neutral"  # The emotion from tag that applies to the paragraph  
        current_text = []  
        
        # Split text into lines  
        lines = text.split('\n')  
        i = 0  
        
        while i < len(lines):  
            line = lines[i].strip()  
            
            # Check for emotion tag format: <emotion>emotion_name</emotion>  
            emotion_tag_match = re.match(r'<emotion>(\w+)</emotion>', line)  
            if emotion_tag_match:  
                # If we have accumulated text, add it as a segment with the current emotion  
                if current_text:  
                    segments.append(('\n'.join(current_text), paragraph_emotion))  
                    current_text = []  
                    
                # Update the paragraph emotion  
                emotion_name = emotion_tag_match.group(1).lower()  
                paragraph_emotion = emotion_name if emotion_name in VOICE_EMOTIONS else "neutral"  
                i += 1  
                continue  
            
            # Process non-emotion-tag lines  
            if line:  
                # Check for square bracket emotion within the line  
                bracket_match = re.search(r'\\[(speaking\s+\w+|positive\s+tone|cautious\s+tone|serious\s+tone|.*?)\\]', line)  
                line_emotion = paragraph_emotion  # Default to paragraph emotion  
                
                if bracket_match:  
                    emotion_text = bracket_match.group(1).lower()  
                    # Convert spaces to underscores for matching with VOICE_EMOTIONS  
                    emotion_key = emotion_text.replace(" ", "_")  
                    
                    # If this emotion exists in our dictionary, use it for this line  
                    if emotion_key in VOICE_EMOTIONS:  
                        line_emotion = emotion_key  
                        
                    # Note: We DO NOT remove the bracket notation as it should be kept in the text  
                
                # Add this line as its own segment with the appropriate emotion  
                segments.append((line, line_emotion))  
            elif current_text:  # Empty line but we have accumulated text  
                # This is a paragraph break - reset paragraph emotion  
                paragraph_emotion = "neutral"  
            
            i += 1  
        
        return segments  

    def _generate_audio_chunk(  
        self,  
        text: str,  
        output_file: str,  
        previous_text: str = "",  
        next_text: str = "",  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[str]:  
        """  
        Generate audio for a single chunk of text.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            previous_text: Previous text for context  
            next_text: Next text for context  
            voice: Voice to use (defaults to self.voice)  
            emotion: Emotion to apply (neutral, excited, serious, etc.)  
  
        Returns:  
            Optional[str]: Path to the generated audio file or None if failed  
        """  
        voice = voice or self.voice 
        emotion = emotion.replace(" ", "_") if " " in emotion else emotion
  
        if USE_OPENAI_API:  
            result = self._generate_audio_chunk_openai(text, output_file, voice, emotion)  
        else:  
            result = self._generate_audio_chunk_elevenlabs(text, output_file, previous_text, next_text, voice, emotion)  
  
        # Apply post-processing for volume adjustments if needed  
        if result and "volume" in VOICE_EMOTIONS.get(emotion, {}).get(self.provider, {}):  
            try:  
                volume_adjustment = VOICE_EMOTIONS[emotion][self.provider]["volume"]  
                if volume_adjustment != 0:  
                    self._adjust_audio_volume(output_file, volume_adjustment)  
            except Exception as e:  
                error_logger.error(f"Error adjusting audio volume: {e}")  
  
        return result  
  
    def _adjust_audio_volume(self, audio_file: str, volume_adjustment: float):  
        """  
        Adjust the volume of an audio file.  
  
        Args:  
            audio_file: Path to the audio file  
            volume_adjustment: Volume adjustment in dB (positive or negative)  
        """  
        try:  
            audio = AudioSegment.from_file(audio_file)  
            adjusted_audio = audio + volume_adjustment  # dB adjustment  
            adjusted_audio.export(audio_file, format="mp3")  
        except Exception as e:  
            error_logger.error(f"Error adjusting audio volume: {e}")  
  
    def _generate_audio_chunk_openai(  
        self,  
        text: str,  
        output_file: str,  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[str]:  
        """  
        Generate audio chunk using OpenAI TTS API.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            voice: Voice to use  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[str]: Path to the generated audio file or None if failed  
        """  
        try:  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
            voice = voice or self.voice  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("openai", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            # Create TTS request  
            response = self.client.audio.speech.create(  
                model=self.model,  
                voice=voice,  
                input=text,  
                **emotion_settings  
            )  
  
            # Save to file  
            response.stream_to_file(output_file)  
  
            return output_file  
        except Exception as e:  
            error_logger.error(f"Error generating audio with OpenAI: {e}")  
            return None  
  
    def _generate_audio_chunk_elevenlabs(  
        self,  
        text: str,  
        output_file: str,  
        previous_text: str = "",  
        next_text: str = "",  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[str]:  
        """  
        Generate audio chunk using ElevenLabs TTS API.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            previous_text: Previous text for context  
            next_text: Next text for context  
            voice: Voice to use  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[str]: Path to the generated audio file or None if failed  
        """  
        try:  
            # Map voice names to ElevenLabs voice IDs  
            voice_mapping = {  
                "alloy": "Rachel",  
                "echo": "Antoni",  
                "fable": "Domi",  
                "onyx": "Josh",  
                "nova": "Bella",  
                "shimmer": "Sam"  
            }  
  
            # Default to the configured voice if not specified  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
            voice = voice or self.voice  
  
            # Map to ElevenLabs voice  
            elevenlabs_voice = voice_mapping.get(voice, "Bella")  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("elevenlabs", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            # Generate audio  
            audio = self.client.generate(  
                voice=elevenlabs_voice,  
                text=text,  
                model_id="eleven_turbo_v2",  
                output_format="mp3_44100_64",  
                previous_text=previous_text,  
                next_text=next_text,  
                **emotion_settings  
            )  
  
            # Write the audio to file  
            with open(output_file, "wb") as f:  
                f.write(audio)  
  
            return output_file  
        except Exception as e:  
            error_logger.error(f"Error generating audio with ElevenLabs: {e}")  
            return None  
  
    def _merge_audio_files(self, chunk_files: List[str], output_path: str, pause_duration: int = 500):  
        """  
        Merge multiple audio files into one.  
  
        Args:  
            chunk_files: List of audio file paths to merge  
            output_path: Path to save the merged audio file  
            pause_duration: Duration of pause between chunks in milliseconds  
        """  
        try:  
            # Load the first file  
            combined = AudioSegment.from_mp3(chunk_files[0])  
  
            # Add pause between chunks  
            pause = AudioSegment.silent(duration=pause_duration)  
  
            # Append the rest  
            for chunk_file in chunk_files[1:]:  
                audio_chunk = AudioSegment.from_mp3(chunk_file)  
                combined += pause + audio_chunk  
  
            # Export the final file  
            combined.export(output_path, format="mp3")  
        except Exception as e:  
            error_logger.error(f"Error merging audio files: {e}")  
            # If merge fails, copy the first file as fallback  
            if chunk_files:  
                try:  
                    shutil.copy2(chunk_files[0], output_path)  
                except Exception as copy_error:  
                    error_logger.error(f"Error copying fallback audio file: {copy_error}")  
  
    def _generate_audio_chunk_in_memory(  
        self,  
        text: str,  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio for a chunk and return the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        voice = voice or self.voice  
        emotion = emotion.replace(" ", "_") if " " in emotion else emotion
        if USE_OPENAI_API:  
            audio_data = self._generate_audio_chunk_openai_in_memory(text, voice, emotion)  
        else:  
            audio_data = self._generate_audio_chunk_elevenlabs_in_memory(text, voice, emotion)  
  
        # Apply volume adjustments if needed  
        if audio_data and "volume" in VOICE_EMOTIONS.get(emotion, {}).get(self.provider, {}):  
            try:  
                volume_adjustment = VOICE_EMOTIONS[emotion][self.provider]["volume"]  
                if volume_adjustment != 0:  
                    audio_data = self._adjust_audio_volume_in_memory(audio_data, volume_adjustment)  
            except Exception as e:  
                error_logger.error(f"Error adjusting in-memory audio volume: {e}")  
  
        return audio_data  
  
    def _adjust_audio_volume_in_memory(self, audio_data: bytes, volume_adjustment: float) -> bytes:  
        """  
        Adjust the volume of in-memory audio data.  
  
        Args:  
            audio_data: Audio data as bytes  
            volume_adjustment: Volume adjustment in dB (positive or negative)  
  
        Returns:  
            bytes: Adjusted audio data  
        """  
        try:  
            # Load audio from bytes  
            audio = AudioSegment.from_mp3(io.BytesIO(audio_data))  
              
            # Adjust volume  
            adjusted_audio = audio + volume_adjustment  # dB adjustment  
              
            # Export back to bytes  
            buffer = io.BytesIO()  
            adjusted_audio.export(buffer, format="mp3")  
            return buffer.getvalue()  
        except Exception as e:  
            error_logger.error(f"Error adjusting in-memory audio volume: {e}")  
            return audio_data  # Return original if adjustment fails  
  
    def _generate_audio_chunk_openai_in_memory(  
        self,  
        text: str,  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio using OpenAI TTS API and return the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        try:  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
            voice = voice or self.voice  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("openai", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            # Create TTS request  
            response = self.client.audio.speech.create(  
                model=self.model,  
                voice=voice,  
                input=text,  
                **emotion_settings  
            )  
  
            # Get raw audio data  
            return response.content  
        except Exception as e:  
            error_logger.error(f"Error generating in-memory audio with OpenAI: {e}")  
            return None  
  
    def _generate_audio_chunk_elevenlabs_in_memory(  
        self,  
        text: str,  
        voice: str = None,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio using ElevenLabs TTS API and return the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        try:  
            # Map voice names to ElevenLabs voice IDs  
            voice_mapping = {  
                "alloy": "Rachel",  
                "echo": "Antoni",  
                "fable": "Domi",  
                "onyx": "Josh",  
                "nova": "Bella",  
                "shimmer": "Sam"  
            }  
  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
            # Default to the configured voice if not specified  
            voice = voice or self.voice  
  
            # Map to ElevenLabs voice  
            elevenlabs_voice = voice_mapping.get(voice, "Bella")  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("elevenlabs", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            # Generate audio  
            audio = self.client.generate(  
                voice=elevenlabs_voice,  
                text=text,  
                model_id="eleven_turbo_v2",  
                output_format="mp3_44100_64",  
                **emotion_settings  
            )  
  
            return audio  # Already in bytes format  
        except Exception as e:  
            error_logger.error(f"Error generating in-memory audio with ElevenLabs: {e}")  
            return None  
  
class StreamingTTSAgent(TTSAgent):  
    """  
    A TTS Agent that streams audio chunks as they become ready.  
    """  
  
    def __call__(  
        self,  
        text: str,  
        stream: bool = True,  
        **kwargs  
    ) -> Union[Generator[bytes, None, None], str]:  
        """  
        Stream audio chunks as they become ready or return a file path.  
  
        Args:  
            text: Text to convert to speech  
            stream: Whether to stream the output  
            **kwargs: Additional arguments  
  
        Returns:  
            Union[Generator[bytes, None, None], str]: Audio stream or file path  
        """  
        # Determine output path for final storage  
        if self.storage_path.endswith('.mp3'):  
            output_path = self.storage_path  
        else:  
            os.makedirs(self.storage_path, exist_ok=True)  
            output_path = os.path.join(self.storage_path, 'output.mp3')  
  
        # If file exists and we're streaming, stream it directly  
        if stream and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:  
            return self._stream_existing_file(output_path)  
  
        # If not streaming, use the parent class implementation  
        if not stream:  
            return super().__call__(text, **kwargs)  
  
        # Otherwise, process and stream chunks  
        return self.process_chunks(text, output_path, **kwargs)  
  
    def _stream_existing_file(self, file_path: str) -> Generator[bytes, None, None]:  
        """  
        Stream an existing audio file.  
  
        Args:  
            file_path: Path to the audio file  
  
        Returns:  
            Generator[bytes, None, None]: Audio chunks  
        """  
        try:  
            with open(file_path, 'rb') as f:  
                while chunk := f.read(8192):  
                    yield chunk  
        except Exception as e:  
            error_logger.error(f"Error streaming existing file: {e}")  
            yield b''  # Yield empty bytes to avoid breaking the generator  
  
    def process_chunks(  
        self,  
        text: str,  
        output_path: str,  
        **kwargs  
    ) -> Generator[bytes, None, None]:  
        """  
        Process text into chunks and stream audio.  
  
        Args:  
            text: Text to convert to speech  
            output_path: Path to save the final audio file  
            **kwargs: Additional arguments  
  
        Returns:  
            Generator[bytes, None, None]: Audio chunks  
        """  
        next_chunk_index = 0  
        pending_futures = {}  # {index: Future}  
        all_audio_chunks = []  # For final storage  
        paragraph_emotion = "neutral"  # The emotion from tag that applies to the paragraph  
  
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:  
            if self.convert_to_tts_friendly_format and not self.is_tts_friendly(text):  
                # Process streaming LLM output  
                llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])  
                current_chunk = ""  
                chunk_index = 0  
  
                try:  
                    for partial_text in llm(self.prompt.format(text=text), stream=True, **kwargs):  
                        current_chunk += partial_text  
  
                        # Process complete chunks (split by \n\n)  
                        if '\n\n' in current_chunk:  
                            chunks = current_chunk.split('\n\n')  
                            # Keep last incomplete chunk  
                            current_chunk = chunks[-1]  
  
                            # Process complete chunks  
                            for chunk in chunks[:-1]:  
                                if chunk.strip():  
                                    # Parse for emotions  
                                    segments = self._parse_text_with_emotions(chunk.strip())  
                                    for segment_text, emotion in segments:  
                                        if segment_text.strip():  
                                            future = executor.submit(  
                                                self._generate_audio_chunk_in_memory,  
                                                segment_text.strip(),  
                                                self.voice,  
                                                emotion  
                                            )  
                                            pending_futures[chunk_index] = future  
                                            chunk_index += 1  
  
                            # Yield ready chunks in order  
                            for audio_chunk in self._yield_ready_chunks(pending_futures, next_chunk_index, all_audio_chunks):  
                                next_chunk_index += 1  
                                yield audio_chunk  
                except Exception as e:  
                    error_logger.error(f"Error in LLM streaming: {e}")  
  
                # Process final chunk if not empty  
                if current_chunk.strip():  
                    segments = self._parse_text_with_emotions(current_chunk.strip())  
                    for segment_text, emotion in segments:  
                        if segment_text.strip():  
                            future = executor.submit(  
                                self._generate_audio_chunk_in_memory,  
                                segment_text.strip(),  
                                self.voice,  
                                emotion  
                            )  
                            pending_futures[chunk_index] = future  
                            chunk_index += 1  
            else:  
                # Text is already TTS-friendly  
                # Parse for emotions and split into segments  
                segments = self._parse_text_with_emotions(text)  
                for i, (chunk, emotion) in enumerate(segments):  
                    if chunk.strip():  
                        future = executor.submit(  
                            self._generate_audio_chunk_in_memory,  
                            chunk.strip(),  
                            self.voice,  
                            emotion  
                        )  
                        pending_futures[i] = future  
  
            # Yield remaining chunks in order  
            while pending_futures:  
                ready_chunks = list(self._yield_ready_chunks(pending_futures, next_chunk_index, all_audio_chunks))  
                if ready_chunks:  
                    for _ in ready_chunks:  
                        next_chunk_index += 1  
                        yield _  
                else:  
                    # Small sleep to prevent busy waiting  
                    time.sleep(0.1)  
  
        # Save accumulated audio chunks to file  
        self._save_audio_chunks(all_audio_chunks, output_path)  
  
    def _yield_ready_chunks(  
        self,  
        pending_futures: Dict[int, concurrent.futures.Future],  
        next_chunk_index: int,  
        all_audio_chunks: List[bytes]  
    ) -> Generator[bytes, None, None]:  
        """  
        Yield audio chunks that are ready in the correct order.  
  
        Args:  
            pending_futures: Dictionary of pending futures  
            next_chunk_index: Index of the next chunk to yield  
            all_audio_chunks: List to store all audio chunks for final file  
  
        Returns:  
            Generator[bytes, None, None]: Ready audio chunks  
        """  
        while next_chunk_index in pending_futures:  
            future = pending_futures[next_chunk_index]  
            if future.done():  
                try:  
                    mp3_data = future.result()  
                    if mp3_data:  
                        all_audio_chunks.append(mp3_data)  
                        yield mp3_data  
                    del pending_futures[next_chunk_index]  
                    next_chunk_index += 1  
                except Exception as e:  
                    error_logger.error(f"Error getting audio chunk result: {e}")  
                    del pending_futures[next_chunk_index]  
                    next_chunk_index += 1  
            else:  
                break  
  
    def _save_audio_chunks(self, all_audio_chunks: List[bytes], output_path: str):  
        """  
        Save accumulated audio chunks to a file.  
  
        Args:  
            all_audio_chunks: List of audio chunks  
            output_path: Path to save the merged audio file  
        """  
        try:  
            audio_segments = []  
            for chunk_data in all_audio_chunks:  
                segment = AudioSegment.from_mp3(io.BytesIO(chunk_data))  
                audio_segments.append(segment)  
  
            if audio_segments:  
                # Add small pause between chunks  
                pause = AudioSegment.silent(duration=250)  
                combined = audio_segments[0]  
                for segment in audio_segments[1:]:  
                    combined += pause + segment  
  
                combined.export(output_path, format="mp3")  
            else:  
                # Create an empty audio file if no chunks were generated  
                silent = AudioSegment.silent(duration=1000)  
                silent.export(output_path, format="mp3")  
        except Exception as e:  
            error_logger.error(f"Error saving merged audio file: {e}")  
            # Save first chunk if merge fails  
            if all_audio_chunks:  
                try:  
                    with open(output_path, 'wb') as f:  
                        f.write(all_audio_chunks[0])  
                except Exception as write_error:  
                    error_logger.error(f"Error writing fallback audio file: {write_error}")  


# Define standard podcast templates  
PODCAST_TEMPLATES = {  
    "interview": PodcastTemplate(  
        name="Interview",  
        description="Classic interview format with host asking questions and expert providing answers",  
        structure=[  
            "Introduction and welcome",  
            "Main topic discussion",  
            "Audience questions and potential FAQs",  
            "Conclusion and takeaways"  
        ],  
        host_role="Curious interviewer who guides the conversation",  
        expert_role="Knowledgeable specialist who provides detailed insights",  
        intro_template="Welcome to the show! Today we're discussing {topic} with our expert {expert_name}.",  
        outro_template="That's all for today's episode on {topic}. Thanks to {expert_name} for sharing these valuable insights.",  
        transition_phrases=[  
            "Let's move on to discuss...",  
            "That's fascinating. Now I'd like to ask about...",  
            "Shifting gears a bit...",  
            "Let's explore another aspect of this topic..."  
        ],  
        sound_effect_points=["intro", "transition", "outro"]  
    ),  
    "educational": PodcastTemplate(  
        name="Educational",  
        description="Educational format focused on explaining concepts clearly",  
        structure=[  
            "Topic introduction",  
            "Key concept explanation",  
            "Real-world applications",  
            "Common misconceptions",  
            "Summary and further resources"  
        ],  
        host_role="Teacher who asks clarifying questions and summarizes key points",  
        expert_role="Professor who explains concepts in depth with examples",  
        intro_template="Welcome to our learning session on {topic}. I'm joined by {expert_name} who will help us understand this subject.",  
        outro_template="I hope you've learned something valuable about {topic} today. Remember to check our resources for more information.",  
        transition_phrases=[  
            "Now let's break down...",  
            "Could you explain that concept in more detail?",  
            "What's a practical example of this?",  
            "Many people misunderstand this next point..."  
        ],  
        sound_effect_points=["intro", "key_concept", "misconception", "outro"]  
    ),  
  
    "storytelling": PodcastTemplate(  
        name="Storytelling",  
        description="Narrative-driven format that presents information as a story",  
        structure=[  
            "Setting the scene",  
            "Introducing the challenge",  
            "Key developments",  
            "Resolution and outcome",  
            "Lessons and implications"  
        ],  
        host_role="Narrator who guides the story and asks for details",  
        expert_role="Storyteller who provides rich narrative and analysis",  
        intro_template="Today we have a fascinating story about {topic}. {expert_name} will take us through this journey.",  
        outro_template="And that concludes our story about {topic}. Thank you {expert_name} for this compelling narrative.",  
        transition_phrases=[  
            "What happened next?",  
            "That's a crucial turning point...",  
            "How did people respond to this?",  
            "Let's talk about the aftermath..."  
        ],  
        sound_effect_points=["intro", "challenge", "turning_point", "resolution", "outro"]  
    )  
}  
  
  
  
class PodcastAgent(TTSAgent):  
    """  
    A TTS Agent that converts text into a podcast format with different voices for host and expert.  
    """  
  
    def __init__(  
        self,  
        keys: Dict[str, str],  
        storage_path: str,  
        convert_to_tts_friendly_format: bool = True,  
        host_voice: str = "alloy",  
        expert_voice: str = "nova",  
        shortTTS: bool = False,  
        template: str = "interview",  
        background_music: Optional[str] = None,  
        sound_effects_dir: Optional[str] = None,  
        enable_sound_effects: bool = True,  
        pause_duration: int = 500,  
        intro_music_volume: float = -10,  # dB  
        background_music_volume: float = -20,  # dB  
        sound_effect_volume: float = -5,  # dB  
        max_workers: int = None,  
        model: str = "tts-1",  
        audio_format: str = "mp3"  
    ):  
        """  
        Initialize the PodcastAgent.  
  
        Args:  
            keys: API keys for LLM and TTS services  
            storage_path: Path to store the generated audio files  
            convert_to_tts_friendly_format: Whether to convert text to TTS-friendly format  
            host_voice: Voice to use for the host  
            expert_voice: Voice to use for the expert  
            shortTTS: Whether to generate shorter TTS content  
            template: Podcast template to use  
            background_music: Path to background music file  
            sound_effects_dir: Directory containing sound effect files  
            enable_sound_effects: Whether to enable sound effects  
            pause_duration: Duration of pause between segments in milliseconds  
            intro_music_volume: Volume adjustment for intro music in dB  
            background_music_volume: Volume adjustment for background music in dB  
            sound_effect_volume: Volume adjustment for sound effects in dB  
            max_workers: Maximum number of parallel workers  
            enable_caching: Whether to enable audio caching  
  
            audio_format: Output audio format  
        """  
        super().__init__(  
            keys,  
            storage_path,  
            convert_to_tts_friendly_format,  
            shortTTS,  
            host_voice,  # Default voice is host voice  
            model,  
            audio_format,  
            max_workers,  
        )  
  
        self.host_voice = host_voice  
        self.expert_voice = expert_voice  
        self.template_name = template  
        self.template = PODCAST_TEMPLATES.get(template, PODCAST_TEMPLATES["interview"])  
        self.background_music = background_music  
        self.sound_effects_dir = sound_effects_dir  
        self.enable_sound_effects = enable_sound_effects  
        self.pause_duration = pause_duration  
        self.intro_music_volume = intro_music_volume  
        self.background_music_volume = background_music_volume  
        self.sound_effect_volume = sound_effect_volume  
  
        # Update the system prompt for podcast format  
        shortTTS_prompt = stts_podcast_prompt if self.shortTTS else ""  
  
        # Create a more detailed prompt based on the selected template  
        self.system = f"""  
You are an expert podcast script writer specializing in the {self.template.name} format.  
You will be given a text and you need to convert it into a podcast dialogue format between a Host and an Expert.  
  
PODCAST FORMAT: {self.template.name}  
DESCRIPTION: {self.template.description}  
  
STRUCTURE:  
{self._format_structure()}  
  
HOST ROLE:  
{self.template.host_role}  
- Ask questions and guide the conversation  
- Summarize complex points for clarity  
- Provide smooth transitions between topics  
- Sound curious and engaged  
- Use contractions and conversational language  
  
EXPERT ROLE:  
{self.template.expert_role}  
- Provide detailed explanations with examples  
- Share insights and analysis  
- Use a confident, authoritative tone  
- Break down complex concepts into understandable parts  
- Occasionally refer to research or evidence when relevant  
  
FORMAT REQUIREMENTS:  
- ALWAYS use these exact speaker labels:  
  Host: [Host's lines]  
  Expert: [Expert's lines]  
- Start each new speaker on a new line  
- Include natural pauses indicated by [pause] where appropriate  
- Keep sentences under 20 words for better audio delivery  
- Avoid unusual abbreviations or symbols  
- Use *asterisks* for emphasis on important terms  
- Include verbal acknowledgments ("That's interesting", "I see", etc.)  
  
AUDIO DELIVERY OPTIMIZATION:  
- Keep sentences under 20 words for better TTS delivery  
- Avoid unusual abbreviations, symbols, or technical jargon without explanation  
- Include natural pauses indicated by *pause* where appropriate  
- Use contractions and informal language for a more natural sound  
- Indicate emphasis with *asterisks* for important terms  
- Avoid tongue twisters or words that might be mispronounced by TTS  
  
EMOTION CONTROL:  
- You can use emotion tags to indicate how a line should be spoken. Place the emotion tag on its own line before the speaker's line:  
  <emotion>excited</emotion>  
  Host: [speaking excitedly] This is really fascinating!  
- Available emotions include: neutral, excited, serious, curious, thoughtful, enthusiastic, cautious, surprised, happy, sad, angry, authoritative, humorous, wistful, optimistic, pensive, anxious, whisper, loud, shouting, soft, dramatic, mysterious, urgent, calm, and more.  
- You can also use bracket notation within lines: [speaking thoughtfully], [positive tone], etc.  
- Keep the actual text free of hype and keep it natural, but add emotions to make it more engaging.  

{tts_friendly_format_instructions}  
{shortTTS_prompt}  
  
EXAMPLE OUTPUT FORMAT:  
<emotion>curious</emotion>  
Host: [speaking curiously] Welcome to our podcast! Today we're discussing quantum computing. Could you start by explaining what quantum computing actually is?  
  
<emotion>authoritative</emotion>  
Expert: [speaking authoritatively] Absolutely. Quantum computing uses the principles of quantum mechanics to process information in ways that classical computers can't. Instead of using bits that are either 0 or 1, quantum computers use quantum bits or qubits that can exist in multiple states simultaneously.  
  
<emotion>excited</emotion>  
Host: [speaking excitedly] That's fascinating! So it's like being able to check multiple solutions at once?  
  
<emotion>enthusiastic</emotion>  
Expert: [speaking enthusiastically] Exactly. This property, called superposition, allows quantum computers to explore many possibilities simultaneously...  
  
Ensure you maintain all the original information while making it engaging as a podcast.  
"""  
  
        self.prompt = self.system + f"""  
Original text to convert to podcast format:  
<|context|>  
{{text}}  
</|context|>\n\n  

{shortTTS_prompt}  
Write a podcast script between a Host and an Expert using the above guidelines:  
"""  
  
    def _format_structure(self) -> str:  
        """Format the podcast structure as a numbered list."""  
        return "\n".join([f"{i+1}. {item}" for i, item in enumerate(self.template.structure)])  
  
    def is_podcast_format(self, text: str) -> bool:  
        """  
        Check if the text is already in podcast format.  
  
        Args:  
            text: The text to check  
  
        Returns:  
            bool: True if text is in podcast format, False otherwise  
        """  
        # Look for "Host:" and "Expert:" patterns with more robust regex  
        host_pattern = re.compile(r'^(?:host|presenter|moderator)\s*:', re.IGNORECASE | re.MULTILINE)  
        expert_pattern = re.compile(r'^(?:expert|specialist|guest)\s*:', re.IGNORECASE | re.MULTILINE)  
  
        return bool(host_pattern.search(text)) and bool(expert_pattern.search(text))  
  
    def make_tts_friendly(self, text: str, **kwargs) -> str:  
        """  
        Convert text to podcast format if it's not already.  
  
        Args:  
            text: The text to convert  
            **kwargs: Additional arguments for the LLM call  
  
        Returns:  
            str: Text in podcast format  
        """  
        if self.convert_to_tts_friendly_format and not self.is_podcast_format(text):  
            try:  
                llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])  
                return llm(self.prompt.format(text=text), **kwargs)  
            except Exception as e:  
                error_logger.error(f"Error converting to podcast format: {e}")  
                # Create a simple podcast format as fallback  
                return f"Host: Let's discuss the following information.\n\n{text}\n\nExpert: That's a great summary of the topic."  
        else:  
            return text  
  
    def parse_podcast_segments(self, text: str) -> List[Tuple[str, str, Optional[str]]]:  
        """  
        Parse podcast text into segments with speaker identification and emotion hints.  
        
        Handles two types of emotions:  
        1. Tag-based emotions (<emotion>excited</emotion>) - Apply to all lines until next empty line or emotion tag  
        2. Square bracket emotions ([speaking thoughtfully]) - Apply only to current line, override tag emotion  
        
        Args:  
            text: Podcast format text  
            
        Returns:  
            List[Tuple[str, str, Optional[str]]]: List of (speaker, text, emotion) tuples  
        """  
        try:  
            segments = []  
            lines = text.split('\n')  
            current_speaker = None  
            current_text = []  
            paragraph_emotion = "neutral"  # The emotion from tag that applies to the paragraph  
            i = 0  
            
            while i < len(lines):  
                line = lines[i].strip()  
                
                # Skip empty lines but reset paragraph emotion  
                if not line:  
                    # If we have accumulated text, add it as a segment  
                    if current_speaker and current_text:  
                        segments.append((current_speaker, '\n'.join(current_text), paragraph_emotion))  
                        current_text = []  
                    
                    # Reset paragraph emotion at paragraph breaks  
                    paragraph_emotion = "neutral"  
                    i += 1  
                    continue  
                
                # Check for emotion tag format: <emotion>emotion_name</emotion>  
                emotion_tag_match = re.match(r'<emotion>(\w+)</emotion>', line)  
                if emotion_tag_match:  
                    # If we have accumulated text, add it as a segment  
                    if current_speaker and current_text:  
                        segments.append((current_speaker, '\n'.join(current_text), paragraph_emotion))  
                        current_text = []  
                    
                    # Update the paragraph emotion  
                    emotion_name = emotion_tag_match.group(1).lower()  
                    paragraph_emotion = emotion_name if emotion_name in VOICE_EMOTIONS else "neutral"  
                    i += 1  
                    continue  
                
                # Check for host/expert labels  
                host_match = re.match(r'^(?:host|presenter|moderator)\s*:(.*)', line, re.IGNORECASE)  
                expert_match = re.match(r'^(?:expert|specialist|guest)\s*:(.*)', line, re.IGNORECASE)  
                
                if host_match or expert_match:  
                    # Save previous segment if exists  
                    if current_speaker and current_text:  
                        segments.append((current_speaker, '\n'.join(current_text), paragraph_emotion))  
                        current_text = []  
                    
                    # Set new speaker  
                    current_speaker = "host" if host_match else "expert"  
                    
                    # Extract text after speaker label  
                    text_part = (host_match.group(1) if host_match else expert_match.group(1)).strip()  
                    
                    # Check for square bracket emotion within the line  
                    bracket_match = re.search(r'\\[(speaking\s+\w+|positive\s+tone|cautious\s+tone|serious\s+tone|.*?)\\]', text_part)  
                    line_emotion = paragraph_emotion  # Default to paragraph emotion  
                    
                    if bracket_match:  
                        emotion_text = bracket_match.group(1).lower()  
                        # Convert spaces to underscores for matching with VOICE_EMOTIONS  
                        emotion_key = emotion_text.replace(" ", "_")  
                        
                        # If this emotion exists in our dictionary, use it for this line  
                        if emotion_key in VOICE_EMOTIONS:  
                            line_emotion = emotion_key  
                        
                        # Note: We DO NOT remove the bracket notation as it should be kept in the text  
                    
                    if text_part:  
                        # Add this line as its own segment with the appropriate emotion  
                        segments.append((current_speaker, text_part, line_emotion))  
                    
                    # Reset for next lines  
                    current_text = []  
                else:  
                    # Check for square bracket emotion within the line  
                    bracket_match = re.search(r'\\[(speaking\s+\w+|positive\s+tone|cautious\s+tone|serious\s+tone|.*?)\\]', line)  
                    line_emotion = paragraph_emotion  # Default to paragraph emotion  
                    
                    if bracket_match:  
                        emotion_text = bracket_match.group(1).lower()  
                        # Convert spaces to underscores for matching with VOICE_EMOTIONS  
                        emotion_key = emotion_text.replace(" ", "_")  
                        
                        # If this emotion exists in our dictionary, use it for this line  
                        if emotion_key in VOICE_EMOTIONS:  
                            line_emotion = emotion_key  
                        
                        # Note: We DO NOT remove the bracket notation as it should be kept in the text  
                    
                    # Continue with current speaker if we have one  
                    if current_speaker:  
                        # Add this line as its own segment with the appropriate emotion  
                        segments.append((current_speaker, line, line_emotion))  
                
                i += 1  
            
            # Add the last segment if needed  
            if current_speaker and current_text:  
                segments.append((current_speaker, '\n'.join(current_text), paragraph_emotion))  
            
            return segments  
        except Exception as e:  
            error_logger.error(f"Error parsing podcast segments: {e}")  
            # Return a simple fallback segment  
            return [("host", text, "neutral")]  

    
    def __call__(  
        self,  
        text: str,  
        topic: str = None,  
        expert_name: str = "Dr. Expert",  
        **kwargs  
    ) -> str:  
        """  
        Generate podcast audio with different voices for host and expert.  
  
        Args:  
            text: Text to convert to podcast audio  
            topic: Topic of the podcast (for template placeholders)  
            expert_name: Name of the expert (for template placeholders)  
            **kwargs: Additional arguments  
  
        Returns:  
            str: Path to the generated audio file  
        """  
        # Set default topic if not provided  
        topic = topic or "this subject"  
  
        # Convert to podcast format if needed  
        text = self.make_tts_friendly(text, **kwargs)  
        text = text.replace("</emotion>\n\n", "</emotion>\n")
  
        # Apply template placeholders  
        text = self._apply_template_placeholders(text, topic, expert_name)  
  
        # Parse into speaker segments  
        try:  
            segments = self.parse_podcast_segments(text)  
        except Exception as e:  
            error_logger.error(f"Error parsing podcast segments: {e}")  
            segments = [("host", text, "neutral")]  
  
        # Create temporary directory  
        with tempfile.TemporaryDirectory() as temp_dir:  
            segment_files = []  
            sound_effect_files = []  
  
            # Process segments in parallel  
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:  
                futures = []  
  
                # Add intro sound effect if enabled  
                if self.enable_sound_effects and self.sound_effects_dir:  
                    intro_effect = self._get_sound_effect_path("intro")  
                    if intro_effect:  
                        intro_file = os.path.join(temp_dir, 'intro_effect.mp3')  
                        futures.append(  
                            executor.submit(  
                                self._process_sound_effect,  
                                intro_effect,  
                                intro_file,  
                                self.intro_music_volume  
                            )  
                        )  
                        sound_effect_files.append(("intro", 0))  # Position 0  
  
                # Submit tasks for each segment  
                for i, (speaker, segment_text, emotion) in enumerate(segments):  
                    if segment_text.strip():  # Skip empty segments  
                        temp_file = os.path.join(temp_dir, f'segment_{i}.mp3')  
  
                        # Choose voice based on speaker  
                        voice = self.host_voice if speaker == "host" else self.expert_voice  
  
                        futures.append(  
                            executor.submit(  
                                self._generate_audio_segment,  
                                segment_text.strip(),  
                                temp_file,  
                                voice,  
                                emotion  
                            )  
                        )  
  
                        # Add sound effects at appropriate positions  
                        if self.enable_sound_effects and self.sound_effects_dir:  
                            # Check if this segment contains a transition phrase  
                            for phrase in self.template.transition_phrases:  
                                if phrase.lower() in segment_text.lower():  
                                    transition_effect = self._get_sound_effect_path("transition")  
                                    if transition_effect:  
                                        effect_file = os.path.join(temp_dir, f'transition_effect_{i}.mp3')  
                                        futures.append(  
                                            executor.submit(  
                                                self._process_sound_effect,  
                                                transition_effect,  
                                                effect_file,  
                                                self.sound_effect_volume  
                                            )  
                                        )  
                                        sound_effect_files.append(("transition", i + 0.5))  # Position after segment  
                                        break  
  
                            # Check for specific sound effect points in the template  
                            for effect_point in self.template.sound_effect_points:  
                                if effect_point == "intro" and i == 0:  
                                    continue  # Already added intro effect  
                                if effect_point == "outro" and i == len(segments) - 1:  
                                    outro_effect = self._get_sound_effect_path("outro")  
                                    if outro_effect:  
                                        effect_file = os.path.join(temp_dir, f'outro_effect.mp3')  
                                        futures.append(  
                                            executor.submit(  
                                                self._process_sound_effect,  
                                                outro_effect,  
                                                effect_file,  
                                                self.sound_effect_volume  
                                            )  
                                        )  
                                        sound_effect_files.append(("outro", float(len(segments))))  # Position at end  
  
                                # Check for other effect points in the text  
                                effect_keywords = {  
                                    "key_concept": ["key concept", "important point", "essential idea"],  
                                    "misconception": ["misconception", "common mistake", "often misunderstood"],  
                                    "perspective_shift": ["different perspective", "another view", "alternative approach"],  
                                    "agreement": ["we agree", "common ground", "both sides agree"],  
                                    "challenge": ["challenge", "problem", "difficult situation"],  
                                    "turning_point": ["turning point", "pivotal moment", "critical juncture"],  
                                    "resolution": ["resolution", "solution", "outcome"]  
                                }  
  
                                for effect_name, keywords in effect_keywords.items():  
                                    if effect_point == effect_name and any(keyword.lower() in segment_text.lower() for keyword in keywords):  
                                        effect_path = self._get_sound_effect_path(effect_name)  
                                        if effect_path:  
                                            effect_file = os.path.join(temp_dir, f'{effect_name}_effect_{i}.mp3')  
                                            futures.append(  
                                                executor.submit(  
                                                    self._process_sound_effect,  
                                                    effect_path,  
                                                    effect_file,  
                                                    self.sound_effect_volume  
                                                )  
                                            )  
                                            sound_effect_files.append((effect_name, i + 0.5))  # Position after segment  
                                            break  
  
                # Collect results  
                segment_results = {}  
                effect_results = {}  
  
                for future in concurrent.futures.as_completed(futures):  
                    try:  
                        result = future.result()  
                        if result:  
                            file_path, file_type, position = result  
                            if file_type == "segment":  
                                segment_results[position] = file_path  
                            elif file_type == "effect":  
                                effect_results[position] = file_path  
                    except Exception as e:  
                        error_logger.error(f"Error processing audio: {e}")  
  
            # Combine segments and sound effects in the correct order  
            ordered_files = []  
  
            # Add segments  
            for i in range(len(segments)):  
                if i in segment_results:  
                    ordered_files.append(segment_results[i])  
  
            # Add sound effects at their positions  
            for effect_name, position in sound_effect_files:  
                position_key = float(position)  # Convert to float for dictionary lookup  
                if position_key in effect_results:  
                    # Insert at the appropriate position  
                    insert_index = min(int(position_key) + 1, len(ordered_files))  
                    ordered_files.insert(insert_index, effect_results[position_key])  
  
            # Determine final output path  
            if self.storage_path.endswith('.mp3'):  
                output_path = self.storage_path  
            else:  
                os.makedirs(self.storage_path, exist_ok=True)  
                output_path = os.path.join(self.storage_path, 'podcast_output.mp3')  
  
            # Merge audio files with background music if available  
            if ordered_files:  
                self._merge_podcast_audio(ordered_files, output_path)  
            else:  
                # Create an empty audio file if no segments were generated  
                silent = AudioSegment.silent(duration=3000)  
                silent.export(output_path, format="mp3")  
                error_logger.error("No podcast segments were successfully generated")  
  
        return output_path  
  
    def _apply_template_placeholders(self, text: str, topic: str, expert_name: str) -> str:  
        """  
        Apply template placeholders to the podcast text.  
  
        Args:  
            text: Podcast text  
            topic: Topic of the podcast  
            expert_name: Name of the expert  
  
        Returns:  
            str: Text with placeholders replaced  
        """  
        # Check if the text already has an introduction 
        
        if not text.startswith("Host:") and not (text.startswith("<emotion>") and "Host:" in text.split("\n", 2)[1]):  
            # Add template intro  
            intro = self.template.intro_template.format(topic=topic, expert_name=expert_name)  
            text = f"Host: {intro}\n\n{text}"  
  
        # Check if the text already has a conclusion  
        if not text.strip().endswith("Expert:") and not any(text.strip().endswith(f"Expert: {line}") for line in self.template.outro_template.split('\n')):  
            # Add template outro  
            outro = self.template.outro_template.format(topic=topic, expert_name=expert_name)  
            text = f"{text}\n\nHost: {outro}"  
  
        return text  
  
    def _generate_audio_segment(  
        self,  
        text: str,  
        output_file: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Tuple[str, str, int]:  
        """  
        Generate audio for a single segment with the specified voice and emotion.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Tuple[str, str, int]: (file_path, file_type, position)  
        """  
        try:  
            # Generate new audio  
            if USE_OPENAI_API:  
                result = self._generate_audio_segment_openai(text, output_file, voice, emotion)  
            else:  
                result = self._generate_audio_segment_elevenlabs(text, output_file, voice, emotion)  
  
            if result:  
                # Extract position from filename  
                position = int(re.search(r'segment_(\d+)', output_file).group(1))  
                return (output_file, "segment", position)  
            return None  
        except Exception as e:  
            error_logger.error(f"Error generating audio segment: {e}")  
            return None  
  
    def _generate_audio_segment_openai(  
        self,  
        text: str,  
        output_file: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Optional[str]:  
        """  
        Generate audio segment using OpenAI TTS API.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[str]: Path to the generated audio file or None if failed  
        """  
        try:  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("openai", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            response = self.client.audio.speech.create(  
                model=self.model,  
                voice=voice,  
                input=text,  
                **emotion_settings  
            )  
            
  
            response.stream_to_file(output_file)  
  
            # Apply volume adjustment if needed  
            if "volume" in VOICE_EMOTIONS.get(emotion, {}).get("openai", {}):  
                volume_adjustment = VOICE_EMOTIONS[emotion]["openai"]["volume"]  
                if volume_adjustment != 0:  
                    self._adjust_audio_volume(output_file, volume_adjustment)  
  
            return output_file  
        except Exception as e:  
            error_logger.error(f"Error generating audio with OpenAI: {e}")  
            return None  
  
    def _generate_audio_segment_elevenlabs(  
        self,  
        text: str,  
        output_file: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Optional[str]:  
        """  
        Generate audio segment using ElevenLabs TTS API.  
  
        Args:  
            text: Text to convert to speech  
            output_file: Path to save the audio file  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[str]: Path to the generated audio file or None if failed  
        """  
        try:  
            # Map voice names to ElevenLabs voice IDs  
            voice_mapping = {  
                "alloy": "Rachel",  
                "echo": "Antoni",  
                "fable": "Domi",  
                "onyx": "Josh",  
                "nova": "Bella",  
                "shimmer": "Sam"  
            }  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion
  
            # Map to ElevenLabs voice  
            elevenlabs_voice = voice_mapping.get(voice, "Bella")  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("elevenlabs", {}).copy()  
              
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            audio = self.client.generate(  
                voice=elevenlabs_voice,  
                text=text,  
                model_id="eleven_turbo_v2",  
                output_format="mp3_44100_64",  
                **emotion_settings  
            )  
  
            # Write the audio to file  
            with open(output_file, "wb") as f:  
                f.write(audio)  
  
            # Apply volume adjustment if needed  
            if "volume" in VOICE_EMOTIONS.get(emotion, {}).get("elevenlabs", {}):  
                volume_adjustment = VOICE_EMOTIONS[emotion]["elevenlabs"]["volume"]  
                if volume_adjustment != 0:  
                    self._adjust_audio_volume(output_file, volume_adjustment)  
  
            return output_file  
        except Exception as e:  
            error_logger.error(f"Error generating audio with ElevenLabs: {e}")  
            return None  
  
    def _get_sound_effect_path(self, effect_name: str) -> Optional[str]:  
        """  
        Get the path to a sound effect file.  
  
        Args:  
            effect_name: Name of the sound effect  
  
        Returns:  
            Optional[str]: Path to the sound effect file or None if not found  
        """  
        if not self.sound_effects_dir:  
            return None  
  
        effect_filename = SOUND_EFFECTS.get(effect_name)  
        if not effect_filename:  
            return None  
  
        effect_path = os.path.join(self.sound_effects_dir, effect_filename)  
        if os.path.exists(effect_path):  
            return effect_path  
  
        # Try with different extensions if the exact file doesn't exist  
        for ext in ['.mp3', '.wav', '.ogg']:  
            base_name = os.path.splitext(effect_filename)[0]  
            alt_path = os.path.join(self.sound_effects_dir, f"{base_name}{ext}")  
            if os.path.exists(alt_path):  
                return alt_path  
  
        return None  
  
    def _process_sound_effect(  
        self,  
        effect_path: str,  
        output_file: str,  
        volume_adjustment: float  
    ) -> Tuple[str, str, float]:  
        """  
        Process a sound effect file (adjust volume, etc.).  
  
        Args:  
            effect_path: Path to the sound effect file  
            output_file: Path to save the processed file  
            volume_adjustment: Volume adjustment in dB  
  
        Returns:  
            Tuple[str, str, float]: (file_path, file_type, position)  
        """  
        try:  
            effect = AudioSegment.from_file(effect_path)  
  
            # Adjust volume  
            effect = effect + volume_adjustment  # dB adjustment  
  
            # Export processed effect  
            effect.export(output_file, format="mp3")  
  
            # Extract position from filename  
            position_match = re.search(r'(\w+)_effect_(\d+|$)', os.path.basename(output_file))  
            if position_match:  
                effect_type = position_match.group(1)  
                if position_match.group(2):  
                    position = float(position_match.group(2))  
                else:  
                    # Handle intro/outro cases  
                    if effect_type == "intro":  
                        position = 0.0  
                    elif effect_type == "outro":  
                        position = 999.0  # Very high number to ensure it's at the end  
                    else:  
                        position = 0.0  
            else:  
                position = 0.0  
  
            return (output_file, "effect", position)  
        except Exception as e:  
            error_logger.error(f"Error processing sound effect: {e}")  
            return None  
  
    def _merge_podcast_audio(self, audio_files: List[str], output_path: str):  
        """  
        Merge podcast audio files with background music if available.  
  
        Args:  
            audio_files: List of audio file paths to merge  
            output_path: Path to save the merged audio file  
        """  
        try:  
            if not audio_files:  
                error_logger.error("No audio files to merge")  
                return  
  
            # Load all audio segments  
            segments = []  
            for file_path in audio_files:  
                try:  
                    segment = AudioSegment.from_mp3(file_path)  
                    segments.append(segment)  
                except Exception as e:  
                    error_logger.error(f"Error loading audio segment {file_path}: {e}")  
  
            if not segments:  
                error_logger.error("No valid audio segments to merge")  
                return  
  
            # Add pause between segments  
            pause = AudioSegment.silent(duration=self.pause_duration)  
  
            # Merge segments  
            combined = segments[0]  
            for segment in segments[1:]:  
                combined += pause + segment  
  
            # Add background music if available  
            if self.background_music and os.path.exists(self.background_music):  
                try:  
                    background = AudioSegment.from_file(self.background_music)  
  
                    # Loop background music if needed  
                    if len(background) < len(combined):  
                        loops_needed = int(len(combined) / len(background)) + 1  
                        looped_background = background * loops_needed  
                        background = looped_background[:len(combined)]  
                    else:  
                        background = background[:len(combined)]  
  
                    # Adjust background volume  
                    background = background + self.background_music_volume  # dB adjustment  
  
                    # Overlay background with podcast audio  
                    combined = combined.overlay(background)  
                except Exception as e:  
                    error_logger.error(f"Error adding background music: {e}")  
  
            # Export the final file  
            combined.export(output_path, format="mp3")  
        except Exception as e:  
            error_logger.error(f"Error merging podcast audio: {e}")  
            # If merge fails, copy the first file as fallback  
            if audio_files:  
                try:  
                    shutil.copy2(audio_files[0], output_path)  
                except Exception as copy_error:  
                    error_logger.error(f"Error copying fallback audio file: {copy_error}")  
  
class StreamingPodcastAgent(PodcastAgent):  
    """  
    A streaming-first podcast TTS agent that processes and converts text to podcast audio in real-time.  
    """  
  
    def __call__(  
        self,  
        text: str,  
        topic: str = None,  
        expert_name: str = "Dr. Expert",  
        stream: bool = True, 
        
        **kwargs  
    ) -> Union[Generator[bytes, None, None], str]:  
        """  
        Stream podcast audio chunks as they become ready or return a file path.  
  
        Args:  
            text: Text to convert to podcast audio  
            topic: Topic of the podcast (for template placeholders)  
            expert_name: Name of the expert (for template placeholders)  
            stream: Whether to stream the output  
            **kwargs: Additional arguments  
  
        Returns:  
            Union[Generator[bytes, None, None], str]: Audio stream or file path  
        """  
        # Determine output path for final storage  
        if self.storage_path.endswith('.mp3'):  
            output_path = self.storage_path  
        else:  
            os.makedirs(self.storage_path, exist_ok=True)  
            output_path = os.path.join(self.storage_path, 'podcast_output.mp3')  
  
        # If file exists and we're streaming, stream it directly  
        if stream and os.path.exists(output_path) and os.path.getsize(output_path) > 1024:  
            return self._stream_existing_file(output_path)  
  
        # If not streaming, use the parent class implementation  
        if not stream:  
            return super().__call__(text, topic, expert_name, **kwargs)  
  
        # Otherwise, process and stream chunks  
        return self.process_podcast_chunks(text, output_path, topic, expert_name, **kwargs)  
  
    def _stream_existing_file(self, file_path: str) -> Generator[bytes, None, None]:  
        """  
        Stream an existing audio file.  
  
        Args:  
            file_path: Path to the audio file  
  
        Returns:  
            Generator[bytes, None, None]: Audio chunks  
        """  
        try:  
            with open(file_path, 'rb') as f:  
                while chunk := f.read(8192):  
                    yield chunk  
        except Exception as e:  
            error_logger.error(f"Error streaming existing file: {e}")  
            yield b''  # Yield empty bytes to avoid breaking the generator  
  
    def process_podcast_chunks(  
        self,  
        text: str,  
        output_path: str,  
        topic: str = None,  
        expert_name: str = "Dr. Expert",  
        **kwargs  
    ) -> Generator[bytes, None, None]:  
        """  
        Process text into podcast format and generate audio chunks in streaming fashion.  
  
        Args:  
            text: Text to convert to podcast audio  
            output_path: Path to save the final audio file  
            topic: Topic of the podcast (for template placeholders)  
            expert_name: Name of the expert (for template placeholders)  
            **kwargs: Additional arguments  
  
        Returns:  
            Generator[bytes, None, None]: Audio chunks  
        """  
        # Set default topic if not provided  
        topic = topic or "this subject"  
  
        next_chunk_index = 0  
        pending_futures = {}  # {index: Future}  
        all_audio_chunks = []  # For final storage  
  
        # Convert to podcast format  
        if self.convert_to_tts_friendly_format and not self.is_podcast_format(text):  
            try:  
                llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])  
                podcast_script = llm(self.prompt.format(text=text), **kwargs)  
            except Exception as e:  
                error_logger.error(f"Error converting to podcast format: {e}")  
                # Create a simple podcast format as fallback  
                podcast_script = f"Host: Let's discuss the following information.\n\n{text}\n\nExpert: That's a great summary of the topic."  
        else:  
            podcast_script = text  
  
        # Clean up emotion tags  
        podcast_script = podcast_script.replace("</emotion>\n\n", "</emotion>\n")  
  
        # Apply template placeholders  
        podcast_script = self._apply_template_placeholders(podcast_script, topic, expert_name)  
  
        # Parse into speaker segments  
        try:  
            segments = self.parse_podcast_segments(podcast_script)  
        except Exception as e:  
            error_logger.error(f"Error parsing podcast segments: {e}")  
            segments = [("host", podcast_script, "neutral")]  
  
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:  
            # Process intro sound effect if enabled  
            intro_future = None  
            if self.enable_sound_effects and self.sound_effects_dir:  
                intro_effect = self._get_sound_effect_path("intro")  
                if intro_effect:  
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:  
                        intro_file = temp_file.name  
                    intro_future = executor.submit(  
                        self._generate_sound_effect_in_memory,  
                        intro_effect,  
                        self.intro_music_volume  
                    )  
  
            # Submit each segment for TTS processing with appropriate voice  
            segment_futures = []  
            for i, (speaker, segment_text, emotion) in enumerate(segments):  
                if segment_text.strip():  
                    voice = self.host_voice if speaker == "host" else self.expert_voice  
                    future = executor.submit(  
                        self._generate_audio_segment_in_memory,  
                        segment_text.strip(),  
                        voice,  
                        emotion  
                    )  
                    pending_futures[i] = future  
                    segment_futures.append((i, future))  
  
            # Process outro sound effect if enabled  
            outro_future = None  
            if self.enable_sound_effects and self.sound_effects_dir:  
                outro_effect = self._get_sound_effect_path("outro")  
                if outro_effect:  
                    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:  
                        outro_file = temp_file.name  
                    outro_future = executor.submit(  
                        self._generate_sound_effect_in_memory,  
                        outro_effect,  
                        self.sound_effect_volume  
                    )  
  
            # Yield intro sound effect if ready  
            if intro_future and intro_future.done():  
                try:  
                    intro_data = intro_future.result()  
                    if intro_data:  
                        all_audio_chunks.append(intro_data)  
                        yield intro_data  
                except Exception as e:  
                    error_logger.error(f"Error processing intro sound effect: {e}")  
  
            # Yield audio chunks in order as they become ready  
            while pending_futures:  
                if next_chunk_index in pending_futures:  
                    future = pending_futures[next_chunk_index]  
                    if future.done():  
                        try:  
                            mp3_data = future.result()  
                            if mp3_data:  
                                all_audio_chunks.append(mp3_data)  
                                yield mp3_data  
  
                                # Check if we should add a transition sound effect  
                                if self.enable_sound_effects and self.sound_effects_dir:  
                                    speaker, segment_text, _ = segments[next_chunk_index]  
  
                                    # Check for transition phrases  
                                    for phrase in self.template.transition_phrases:  
                                        if phrase.lower() in segment_text.lower():  
                                            transition_effect = self._get_sound_effect_path("transition")  
                                            if transition_effect:  
                                                transition_data = self._generate_sound_effect_in_memory(  
                                                    transition_effect,  
                                                    self.sound_effect_volume  
                                                )  
                                                if transition_data:  
                                                    all_audio_chunks.append(transition_data)  
                                                    yield transition_data  
                                            break  
                        except Exception as e:  
                            error_logger.error(f"Error getting audio chunk result: {e}")  
  
                        del pending_futures[next_chunk_index]  
                        next_chunk_index += 1  
                    else:  
                        # Small sleep to prevent busy waiting  
                        time.sleep(0.1)  
                else:  
                    # Check if we're waiting for chunks that come later in the sequence  
                    if next_chunk_index > max(pending_futures.keys() if pending_futures else [0]):  
                        # We've processed all chunks  
                        break  
                    # Small sleep to prevent busy waiting  
                    time.sleep(0.1)  
  
            # Yield outro sound effect if ready  
            if outro_future:  
                try:  
                    outro_data = outro_future.result()  
                    if outro_data:  
                        all_audio_chunks.append(outro_data)  
                        yield outro_data  
                except Exception as e:  
                    error_logger.error(f"Error processing outro sound effect: {e}")  
  
        # Save accumulated audio chunks to file with background music  
        self._save_podcast_audio_chunks(all_audio_chunks, output_path)  
  
    def _generate_audio_segment_in_memory(  
        self,  
        text: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio for a single segment with the specified voice, returning the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        emotion = emotion.replace(" ", "_") if " " in emotion else emotion  
  
        # Generate new audio  
        if USE_OPENAI_API:  
            audio_data = self._generate_audio_segment_openai_in_memory(text, voice, emotion)  
        else:  
            audio_data = self._generate_audio_segment_elevenlabs_in_memory(text, voice, emotion)  
  
        # Apply volume adjustments if needed  
        if audio_data and "volume" in VOICE_EMOTIONS.get(emotion, {}).get(self.provider, {}):  
            try:  
                volume_adjustment = VOICE_EMOTIONS[emotion][self.provider]["volume"]  
                if volume_adjustment != 0:  
                    audio_data = self._adjust_audio_volume_in_memory(audio_data, volume_adjustment)  
            except Exception as e:  
                error_logger.error(f"Error adjusting in-memory audio volume: {e}")  
  
        return audio_data  
  
    def _generate_audio_segment_openai_in_memory(  
        self,  
        text: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio segment using OpenAI TTS API, returning the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        try:  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("openai", {}).copy()  
  
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            response = self.client.audio.speech.create(  
                model=self.model,  
                voice=voice,  
                input=text,  
                **emotion_settings  
            )  
  
            # Get raw audio data  
            return response.content  
        except Exception as e:  
            error_logger.error(f"Error generating in-memory audio with OpenAI: {e}")  
            return None  
  
    def _generate_audio_segment_elevenlabs_in_memory(  
        self,  
        text: str,  
        voice: str,  
        emotion: str = "neutral"  
    ) -> Optional[bytes]:  
        """  
        Generate audio segment using ElevenLabs TTS API, returning the data in memory.  
  
        Args:  
            text: Text to convert to speech  
            voice: Voice to use for this segment  
            emotion: Emotion to apply  
  
        Returns:  
            Optional[bytes]: Audio data as bytes or None if failed  
        """  
        try:  
            emotion = emotion.replace(" ", "_") if " " in emotion else emotion  
            # Map voice names to ElevenLabs voice IDs  
            voice_mapping = {  
                "alloy": "Rachel",  
                "echo": "Antoni",  
                "fable": "Domi",  
                "onyx": "Josh",  
                "nova": "Bella",  
                "shimmer": "Sam"  
            }  
  
            # Map to ElevenLabs voice  
            elevenlabs_voice = voice_mapping.get(voice, "Bella")  
  
            # Get emotion settings  
            emotion_settings = VOICE_EMOTIONS.get(emotion, {}).get("elevenlabs", {}).copy()  
  
            # Remove volume from settings as it's handled in post-processing  
            if "volume" in emotion_settings:  
                del emotion_settings["volume"]  
  
            # Generate audio  
            audio = self.client.generate(  
                voice=elevenlabs_voice,  
                text=text,  
                model_id="eleven_turbo_v2",  
                output_format="mp3_44100_64",  
                **emotion_settings  
            )  
  
            return audio  # Already in bytes format  
        except Exception as e:  
            error_logger.error(f"Error generating in-memory audio with ElevenLabs: {e}")  
            return None  
  
    def _generate_sound_effect_in_memory(  
        self,  
        effect_path: str,  
        volume_adjustment: float  
    ) -> Optional[bytes]:  
        """  
        Process a sound effect file and return it as bytes.  
  
        Args:  
            effect_path: Path to the sound effect file  
            volume_adjustment: Volume adjustment in dB  
  
        Returns:  
            Optional[bytes]: Sound effect audio data or None if failed  
        """  
        try:  
            effect = AudioSegment.from_file(effect_path)  
  
            # Adjust volume  
            effect = effect + volume_adjustment  # dB adjustment  
  
            # Export to bytes  
            buffer = io.BytesIO()  
            effect.export(buffer, format="mp3")  
            return buffer.getvalue()  
        except Exception as e:  
            error_logger.error(f"Error processing sound effect: {e}")  
            return None  
  
    def _save_podcast_audio_chunks(self, all_audio_chunks: List[bytes], output_path: str):  
        """  
        Save accumulated audio chunks to a file with background music if available.  
  
        Args:  
            all_audio_chunks: List of audio chunks  
            output_path: Path to save the merged audio file  
        """  
        try:  
            audio_segments = []  
            for chunk_data in all_audio_chunks:  
                segment = AudioSegment.from_mp3(io.BytesIO(chunk_data))  
                audio_segments.append(segment)  
  
            if audio_segments:  
                # Add pause between segments  
                pause = AudioSegment.silent(duration=self.pause_duration)  
                combined = audio_segments[0]  
                for segment in audio_segments[1:]:  
                    combined += pause + segment  
  
                # Add background music if available  
                if self.background_music and os.path.exists(self.background_music):  
                    try:  
                        background = AudioSegment.from_file(self.background_music)  
  
                        # Loop background music if needed  
                        if len(background) < len(combined):  
                            loops_needed = int(len(combined) / len(background)) + 1  
                            looped_background = background * loops_needed  
                            background = looped_background[:len(combined)]  
                        else:  
                            background = background[:len(combined)]  
  
                        # Adjust background volume  
                        background = background + self.background_music_volume  # dB adjustment  
  
                        # Overlay background with podcast audio  
                        combined = combined.overlay(background)  
                    except Exception as e:  
                        error_logger.error(f"Error adding background music: {e}")  
  
                combined.export(output_path, format="mp3")  
            else:  
                # Create an empty audio file if no segments were generated  
                silent = AudioSegment.silent(duration=3000)  
                silent.export(output_path, format="mp3")  
                error_logger.error("No podcast segments were successfully generated")  
        except Exception as e:  
            error_logger.error(f"Error saving merged podcast audio file: {e}")  
            # Save first chunk if merge fails  
            if all_audio_chunks:  
                try:  
                    with open(output_path, 'wb') as f:  
                        f.write(all_audio_chunks[0])  
                except Exception as write_error:  
                    error_logger.error(f"Error writing fallback audio file: {write_error}")  


# Code-focused TTS and Podcast Agents for LeetCode-style problems

# Code TTS formatting instructions
code_tts_friendly_format_instructions = """  
**Code TTS Guidelines for Technical Interview and LeetCode-style Problems**:  
  - You are explaining a coding problem and its solution(s) to someone who is listening, not reading code.
  - **NEVER read code verbatim** - instead, explain what the code does in natural language.
  - Focus on the problem understanding, approach, algorithm, and key insights.
  - Use visual and conceptual explanations that work well in audio format.
  
**Problem Explanation Structure**:
  - Start by clearly stating what the problem asks us to do.
  - Give concrete examples with small inputs to illustrate the problem.
  - Mention any constraints or edge cases that are important.
  - Use phrases like "imagine we have...", "picture this scenario...", "think of it as..."
  
**Solution Discussion Format**:
  - Explain the intuition and approach BEFORE any code details.
  - Describe the algorithm in steps using natural language.
  - For data structures, explain WHY we use them, not just WHAT they are.
  - Use analogies and real-world comparisons when possible.
  
**Code Description Guidelines**:
  - Instead of "for i in range(n)", say "we iterate through each element"
  - Instead of "dp[i][j] = max(dp[i-1][j], dp[i][j-1])", say "we take the maximum of the value from the cell above or the cell to the left"
  - Describe the logic and purpose, not the syntax.
  - For complex algorithms, walk through a small example step by step.
  
**Multiple Solutions**:
  - When discussing multiple solutions, clearly transition between them.
  - Compare approaches in terms of time/space complexity using simple terms.
  - Explain trade-offs in practical, understandable language.
  
**Emotion and Pacing**:
  - Use <emotion>curious</emotion> when introducing the problem.
  - Use <emotion>thoughtful</emotion> when explaining the approach.
  - Use <emotion>excited</emotion> when revealing key insights.
  - Use <emotion>authoritative</emotion> when stating the final solution.
  - Add *pause* between major sections for better comprehension.
  
**Technical Terms**:
  - Spell out abbreviations on first use: "BFS, which stands for Breadth-First Search"
  - Use simple language alternatives when possible: "visiting each node" instead of "traversing"
  - Explain Big O notation in practical terms: "linear time, meaning it scales directly with input size"
  
**Additional TTS formatting from base instructions will be included below**
"""

code_stts_prompt = """  
Further Code TTS Instructions (shortTTS = True):  
- Focus ONLY on the core algorithm and key insight.
- Skip detailed complexity analysis unless crucial.
- Give one clear example and move to the solution.
- Mention only the most optimal solution unless specifically asked.
- Keep explanations concise but clear.
- No code reading - pure conceptual explanation.
"""

# Code Podcast formatting instructions  
code_podcast_format_instructions = """
**Code Podcast Guidelines for Technical Interview Discussion**:

You are creating a podcast where a Host interviews an Expert about coding problems and their solutions.
The Host is a curious developer preparing for interviews, and the Expert is a seasoned engineer who explains solutions clearly.

**CONVERSATION STYLE**:
- The Host asks clarifying questions about the problem and approach.
- The Expert explains concepts without reading code verbatim.
- Both speakers use analogies and visual descriptions for audio clarity.
- Natural back-and-forth dialogue with genuine reactions.

**PROBLEM INTRODUCTION PATTERN**:
Host: Introduces the topic and asks about the problem.
Expert: Explains what the problem is asking with a simple example.
Host: Asks about edge cases or clarifications.
Expert: Addresses concerns and sets up the solution approach.

**SOLUTION DISCUSSION PATTERN**:
Expert: Explains the intuition behind the approach.
Host: Asks "why" questions - why this data structure, why this approach?
Expert: Provides reasoning and compares to alternatives.
Host: Summarizes understanding and asks about complexity.
Expert: Confirms and explains trade-offs in simple terms.

**CODE EXPLANATION STYLE**:
- Never say "the code does X" - instead say "our approach does X"
- Use "we" language: "we iterate through", "we check if", "we maintain"
- Describe the algorithm conceptually, not syntactically.
- Walk through examples conversationally.

**MULTIPLE SOLUTIONS DIALOGUE**:
Host: "Is there another way to solve this?"
Expert: Introduces alternative approach with pros/cons.
Host: Asks about when to use which approach.
Expert: Explains practical considerations and interview tips.

**EMOTION GUIDELINES**:
- Host uses <emotion>curious</emotion> for questions.
- Expert uses <emotion>thoughtful</emotion> for explanations.
- Both use <emotion>excited</emotion> for "aha" moments.
- Host uses <emotion>surprised</emotion> for unexpected insights.
- Expert uses <emotion>authoritative</emotion> for key concepts.
"""

code_stts_podcast_prompt = code_stts_prompt + """  
Further Code Podcast Instructions (shortTTS = True):  
- Keep the dialogue snappy and focused.
- Host asks fewer but more targeted questions.
- Expert gives concise, clear explanations.
- Skip extensive examples - one clear walkthrough is enough.
- Focus on the main solution approach and key insight.
"""


class CodeTTSAgent(TTSAgent):
    """
    A specialized TTS Agent for converting LeetCode-style coding problems and solutions
    into audio-friendly explanations. Inherits from TTSAgent but uses code-specific prompts.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        storage_path: str,
        convert_to_tts_friendly_format: bool = True,
        shortTTS: bool = False,
        voice: str = "nova",
        model: str = "tts-1",
        audio_format: str = "mp3",
        max_workers: int = None,
    ):
        """
        Initialize the CodeTTSAgent with code-specific prompts.
        All parameters are the same as TTSAgent.
        """
        # Initialize parent class
        super().__init__(
            keys,
            storage_path,
            convert_to_tts_friendly_format,
            shortTTS,
            voice,
            model,
            audio_format,
            max_workers,
        )
        
        # Override prompts with code-specific versions
        shortTTS_prompt = code_stts_prompt if self.shortTTS else ""
        
        self.system = f"""
You are an expert coding instructor specializing in explaining technical interview problems and LeetCode-style questions.
You convert coding problems and solutions into audio-friendly explanations that are easy to understand when listening.
You NEVER read code verbatim but instead explain algorithms, approaches, and insights in natural language.

Use the following guidelines to create engaging, educational audio content:
{code_tts_friendly_format_instructions}
{tts_friendly_format_instructions}
{shortTTS_prompt}

Remember: Your audience is listening, not reading. Make the content conversational, clear, and conceptual.
"""
        
        self.prompt = self.system + f"""
Original coding problem or solution to explain:
<|context|>
{{text}}
</|context|>

{shortTTS_prompt}
Convert this into an audio-friendly explanation following the Code TTS Guidelines above.
Focus on explaining the problem, approach, and algorithm in a way that's easy to understand through listening:
"""


class StreamingCodeTTSAgent(StreamingTTSAgent):
    """
    A streaming version of CodeTTSAgent that processes and streams code explanations in real-time.
    Inherits from StreamingTTSAgent and overrides prompts for code-specific content.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        storage_path: str,
        convert_to_tts_friendly_format: bool = True,
        shortTTS: bool = False,
        voice: str = "nova",
        model: str = "tts-1",
        audio_format: str = "mp3",
        max_workers: int = None,
    ):
        """
        Initialize the StreamingCodeTTSAgent.
        Inherits from StreamingTTSAgent but uses code-specific prompts.
        """
        # Initialize parent StreamingTTSAgent (which will initialize TTSAgent)
        super().__init__(
            keys,
            storage_path,
            convert_to_tts_friendly_format,
            shortTTS,
            voice,
            model,
            audio_format,
            max_workers,
        )
        
        # Override prompts with code-specific versions (same as CodeTTSAgent)
        shortTTS_prompt = code_stts_prompt if self.shortTTS else ""
        
        self.system = f"""
You are an expert coding instructor specializing in explaining technical interview problems and LeetCode-style questions.
You convert coding problems and solutions into audio-friendly explanations that are easy to understand when listening.
You NEVER read code verbatim but instead explain algorithms, approaches, and insights in natural language.

Use the following guidelines to create engaging, educational audio content:
{code_tts_friendly_format_instructions}
{tts_friendly_format_instructions}
{shortTTS_prompt}

Remember: Your audience is listening, not reading. Make the content conversational, clear, and conceptual.
"""
        
        self.prompt = self.system + f"""
Original coding problem or solution to explain:
<|context|>
{{text}}
</|context|>

{shortTTS_prompt}
Convert this into an audio-friendly explanation following the Code TTS Guidelines above.
Focus on explaining the problem, approach, and algorithm in a way that's easy to understand through listening:
"""


class CodePodcastAgent(PodcastAgent):
    """
    A specialized Podcast Agent for creating conversational podcasts about coding problems and solutions.
    Creates engaging dialogue between a Host and Expert discussing LeetCode-style problems.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        storage_path: str,
        convert_to_tts_friendly_format: bool = True,
        host_voice: str = "alloy",
        expert_voice: str = "nova",
        shortTTS: bool = False,
        template: str = "interview",
        background_music: Optional[str] = None,
        sound_effects_dir: Optional[str] = None,
        enable_sound_effects: bool = True,
        pause_duration: int = 500,
        intro_music_volume: float = -10,
        background_music_volume: float = -20,
        sound_effect_volume: float = -5,
        max_workers: int = None,
        model: str = "tts-1",
        audio_format: str = "mp3"
    ):
        """
        Initialize the CodePodcastAgent with code-specific dialogue prompts.
        All parameters are the same as PodcastAgent.
        """
        # Initialize parent class
        super().__init__(
            keys,
            storage_path,
            convert_to_tts_friendly_format,
            host_voice,
            expert_voice,
            shortTTS,
            template,
            background_music,
            sound_effects_dir,
            enable_sound_effects,
            pause_duration,
            intro_music_volume,
            background_music_volume,
            sound_effect_volume,
            max_workers,
            model,
            audio_format
        )
        
        # Override prompts with code-specific versions
        shortTTS_prompt = code_stts_podcast_prompt if self.shortTTS else ""
        
        self.system = f"""
You are an expert podcast script writer specializing in technical interview preparation and coding problems.
You create engaging dialogues between a Host (curious developer) and an Expert (seasoned engineer) discussing LeetCode-style problems.

The conversation should be educational, engaging, and optimized for audio consumption.
NEVER have speakers read code verbatim - always explain concepts, approaches, and algorithms conversationally.

{code_podcast_format_instructions}

PODCAST FORMAT: {self.template.name}
DESCRIPTION: {self.template.description}

STRUCTURE:
{self._format_structure()}

HOST ROLE (Curious Developer):
- Asks clarifying questions about problem requirements
- Inquires about approach and algorithm choices
- Seeks understanding of time/space complexity
- Asks about edge cases and alternative solutions
- Summarizes understanding and asks follow-ups
- Shows genuine curiosity and "aha" moments

EXPERT ROLE (Seasoned Engineer):
- Explains problems with clear examples
- Describes algorithms conceptually, not syntactically
- Provides intuition behind approaches
- Compares different solutions practically
- Offers interview tips and best practices
- Uses analogies and visual descriptions for audio

{code_tts_friendly_format_instructions}
{tts_friendly_format_instructions}
{shortTTS_prompt}

EXAMPLE DIALOGUE PATTERN:
<emotion>curious</emotion>
Host: [speaking curiously] Today we're tackling an interesting problem about finding the longest palindromic substring. Can you walk us through what this problem is asking?

<emotion>thoughtful</emotion>
Expert: [speaking thoughtfully] Absolutely! Imagine you have a string, and you need to find the longest sequence of characters that reads the same forwards and backwards. For example, in the word "babad", both "bab" and "aba" are palindromes, and they're the longest ones at three characters each.

<emotion>curious</emotion>
Host: [speaking curiously] Interesting! So how would we approach finding these palindromes efficiently?

<emotion>authoritative</emotion>
Expert: [speaking with authority] There are actually several approaches. The key insight is that we can expand around potential centers...

Remember: This is a conversation about code, not a code reading session. Keep it natural and educational!
"""
        
        self.prompt = self.system + f"""
Original coding problem or solution to discuss:
<|context|>
{{text}}
</|context|>

{shortTTS_prompt}
Create an engaging podcast dialogue between a Host and Expert discussing this coding problem.
Focus on explaining the problem, exploring the approach, and understanding the solution through natural conversation:
"""


class StreamingCodePodcastAgent(StreamingPodcastAgent):
    """
    A streaming version of CodePodcastAgent that processes and streams code discussion podcasts in real-time.
    Inherits from StreamingPodcastAgent and overrides prompts for code-specific content.
    """
    
    def __init__(
        self,
        keys: Dict[str, str],
        storage_path: str,
        convert_to_tts_friendly_format: bool = True,
        host_voice: str = "alloy",
        expert_voice: str = "nova",
        shortTTS: bool = False,
        template: str = "interview",
        background_music: Optional[str] = None,
        sound_effects_dir: Optional[str] = None,
        enable_sound_effects: bool = True,
        pause_duration: int = 500,
        intro_music_volume: float = -10,
        background_music_volume: float = -20,
        sound_effect_volume: float = -5,
        max_workers: int = None,
        model: str = "tts-1",
        audio_format: str = "mp3"
    ):
        """
        Initialize the StreamingCodePodcastAgent.
        Inherits from StreamingPodcastAgent but uses code-specific prompts.
        """
        # Initialize parent StreamingPodcastAgent (which will initialize PodcastAgent)
        super().__init__(
            keys,
            storage_path,
            convert_to_tts_friendly_format,
            host_voice,
            expert_voice,
            shortTTS,
            template,
            background_music,
            sound_effects_dir,
            enable_sound_effects,
            pause_duration,
            intro_music_volume,
            background_music_volume,
            sound_effect_volume,
            max_workers,
            model,
            audio_format
        )
        
        # Override prompts with code-specific versions (same as CodePodcastAgent)
        shortTTS_prompt = code_stts_podcast_prompt if self.shortTTS else ""
        
        self.system = f"""
You are an expert podcast script writer specializing in technical interview preparation and coding problems.
You create engaging dialogues between a Host (curious developer) and an Expert (seasoned engineer) discussing LeetCode-style problems.

The conversation should be educational, engaging, and optimized for audio consumption.
NEVER have speakers read code verbatim - always explain concepts, approaches, and algorithms conversationally.

{code_podcast_format_instructions}

PODCAST FORMAT: {self.template.name}
DESCRIPTION: {self.template.description}

STRUCTURE:
{self._format_structure()}

HOST ROLE (Curious Developer):
- Asks clarifying questions about problem requirements
- Inquires about approach and algorithm choices
- Seeks understanding of time/space complexity
- Asks about edge cases and alternative solutions
- Summarizes understanding and asks follow-ups
- Shows genuine curiosity and "aha" moments

EXPERT ROLE (Seasoned Engineer):
- Explains problems with clear examples
- Describes algorithms conceptually, not syntactically
- Provides intuition behind approaches
- Compares different solutions practically
- Offers interview tips and best practices
- Uses analogies and visual descriptions for audio

{code_tts_friendly_format_instructions}
{tts_friendly_format_instructions}
{shortTTS_prompt}

EXAMPLE DIALOGUE PATTERN:
<emotion>curious</emotion>
Host: [speaking curiously] Today we're tackling an interesting problem about finding the longest palindromic substring. Can you walk us through what this problem is asking?

<emotion>thoughtful</emotion>
Expert: [speaking thoughtfully] Absolutely! Imagine you have a string, and you need to find the longest sequence of characters that reads the same forwards and backwards. For example, in the word "babad", both "bab" and "aba" are palindromes, and they're the longest ones at three characters each.

<emotion>curious</emotion>
Host: [speaking curiously] Interesting! So how would we approach finding these palindromes efficiently?

<emotion>authoritative</emotion>
Expert: [speaking with authority] There are actually several approaches. The key insight is that we can expand around potential centers...

Remember: This is a conversation about code, not a code reading session. Keep it natural and educational!
"""
        
        self.prompt = self.system + f"""
Original coding problem or solution to discuss:
<|context|>
{{text}}
</|context|>

{shortTTS_prompt}
Create an engaging podcast dialogue between a Host and Expert discussing this coding problem.
Focus on explaining the problem, exploring the approach, and understanding the solution through natural conversation:
"""

  
if __name__ == "__main__":  
    keys = {  
        "openAIKey": "",  
            }  
    # put keys in os.environ  
    import os  
    for k, v in keys.items():  
        os.environ[k] = v  
    tts = TTSAgent(keys, storage_path="Story_Audio")  
    # Test TTS with a longer story string  
    long_story = (  
        "Once upon a time, in a land far, far away, there was a small village nestled between the mountains and the sea. "  
        "The villagers lived a simple life, farming the fertile land and fishing in the bountiful waters. "  
        "One day, a young boy named Jack discovered a hidden cave while exploring the forest. "  
        "Inside the cave, he found a mysterious old book filled with ancient knowledge and magical spells. "  
        "Jack took the book back to the village, and with the help of the wise old sage, he began to learn the secrets of the past. "  
        "As Jack's knowledge grew, so did his power, and he used his newfound abilities to help the villagers in times of need. "  
        "He healed the sick, brought rain to the parched fields, and protected the village from wild beasts. "  
        "Word of Jack's abilities spread far and wide, and soon people from neighboring villages came to seek his help. "  
        "Jack became a hero, not just in his village, but throughout the land. "  
        "But with great power came great responsibility, and Jack had to learn to balance his duties with his own desires. "  
        "He faced many challenges and made many sacrifices, but in the end, he always stayed true to his heart and his people. "  
        "And so, Jack's legend lived on, inspiring generations to come."  
    )  
    tts(long_story)  
    # Test TTS with a different text about deep learning  
    deep_learning_text = (  
        "Deep learning is a subset of machine learning that is inspired by the structure and function of the brain, "  
        "specifically the neural networks. It is a powerful tool for analyzing large amounts of data and making predictions. "  
        "Deep learning algorithms use multiple layers of neurons to process data, with each layer extracting increasingly complex features. "  
        "This allows deep learning models to learn from raw data and improve their performance over time. "  
        "One of the key advantages of deep learning is its ability to handle unstructured data, such as images, audio, and text. "  
        "This has led to breakthroughs in fields like computer vision, natural language processing, and speech recognition. "  
        "For example, deep learning models can now recognize objects in images with near-human accuracy, translate languages in real-time, "  
        "and even generate realistic human speech. "  
        "Despite its successes, deep learning also has its challenges. Training deep learning models requires large amounts of data and computational power, "  
        "and the models can be difficult to interpret. "  
        "However, researchers are continually developing new techniques to address these challenges and push the boundaries of what deep learning can achieve. "  
        "As the field continues to evolve, deep learning is expected to play an increasingly important role in shaping the future of technology."  
    )  
    podcast = PodcastAgent(keys, storage_path="Podcast_Audio")
    podcast(deep_learning_text)
    # tts_deep_learning = TTSAgent(keys, storage_path="Deep_Learning_Audio")  
    # tts_deep_learning(deep_learning_text)  
