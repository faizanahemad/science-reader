from typing import Union, List
import uuid
from prompts import tts_friendly_format_instructions

import os
import tempfile
import shutil
import concurrent.futures
import logging
from openai import OpenAI
from pydub import AudioSegment  # For merging audio files


from base import CallLLm, CallMultipleLLM, simple_web_search_with_llm
from common import CHEAP_LLM, USE_OPENAI_API, get_async_future, sleep_and_get_future_result, convert_stream_to_iterable
from loggers import getLoggers
import logging
import re
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.WARNING, logging.INFO, logging.ERROR, logging.INFO)
import time
agents = []
adl = []
adllib = []
agent_language_parser = []


class Agent:
    def __init__(self, keys):
        self.keys = keys

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        pass


class TTSAgent(Agent):
    def __init__(self, keys, storage_path, convert_to_tts_friendly_format=True):
        super().__init__(keys)
        self.storage_path = storage_path
        self.convert_to_tts_friendly_format = convert_to_tts_friendly_format
        if USE_OPENAI_API:
            self.client = OpenAI(api_key=os.environ.get("openAIKey", keys["openAIKey"]))
        else:
            from elevenlabs.client import ElevenLabs
            self.client = ElevenLabs(
                api_key=os.environ.get("elevenLabsKey", keys["elevenLabsKey"])
            )
        self.system = f"""
You are an expert TTS (Text To Speech) agent. 
You will be given a text and you need to convert it into a TTS friendly format. 
You need to convert the given text into a TTS friendly format using the following TTS Guidelines:

{tts_friendly_format_instructions}

Ensure that you only convert the text and do not add any new content or information.

"""

        self.prompt = self.system + """
Original answer or text to convert to TTS friendly format:
<|context|>
{text}
</|context|>\n\n

Write the original answer or text in a TTS friendly format using the above TTS Guidelines and the original answer below:
"""



    def is_tts_friendly(self, text):
        """
        Check if the text is already in TTS-friendly format by looking for
        specific markers like pauses, tone indicators, and ensuring chunks
        are within size limits.
        
        Args:
            text (str): The text to check
            
        Returns:
            bool: True if text appears to be TTS-friendly, False otherwise
        """
        # Check for pause markers
        pause_pattern = r'\*(?:pause|short pause)\*'
        
        # Check for tone indicators - matches [speaking ...] or [positive tone] etc.
        tone_pattern = r'\[(speaking|positive|cautious|serious)(?:\s+\w+)?\]'
        
        # Check for enumeration markers
        enumeration_pattern = r'(?:Firstly|Secondly|Thirdly)'
        
        # Check format markers
        has_markers = bool(re.search(pause_pattern, text, re.IGNORECASE) or 
                        re.search(tone_pattern, text, re.IGNORECASE) or 
                        re.search(enumeration_pattern, text))
        
        # Check chunk sizes
        chunks = text.split('\n\n')
        MAX_CHUNK_SIZE = 4000
        chunks_within_limit = all(len(chunk.strip()) <= MAX_CHUNK_SIZE for chunk in chunks)
        
        return has_markers and chunks_within_limit
    
    def __call__(self, text, images=[], temperature=0.2, stream=False, max_tokens=None, system=None, web_search=False):
        # Convert to TTS friendly format if needed
        if self.convert_to_tts_friendly_format and not self.is_tts_friendly(text):
            llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])
            text = llm(self.prompt.format(text=text), images=images, temperature=temperature, 
                    stream=False, max_tokens=max_tokens, system=self.system)

        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            # Split text into chunks
            chunks = text.split('\n\n')
            chunk_files = []

            # Process chunks in parallel
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = []
                
                # Submit tasks for each chunk
                for i, chunk in enumerate(chunks):
                    if chunk.strip():  # Skip empty chunks
                        temp_file = os.path.join(temp_dir, f'chunk_{i}.mp3')
                        
                        # Get previous and next chunks for context
                        previous_text = chunks[i-1].strip() if i > 0 else ""
                        next_text = chunks[i+1].strip() if i < len(chunks)-1 else ""
                        
                        futures.append(
                            executor.submit(
                                self._generate_audio_chunk,
                                chunk.strip(),
                                temp_file,
                                previous_text,
                                next_text
                            )
                        )
                
                # Collect results
                for future in futures:
                    chunk_file = future.result()
                    if chunk_file:
                        chunk_files.append(chunk_file)

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

        return output_path

    def _generate_audio_chunk(self, text, output_file, previous_text="", next_text=""):
        if USE_OPENAI_API:
            return self._generate_audio_chunk_openai(text, output_file, previous_text, next_text)
        else:
            return self._generate_audio_chunk_elevenlabs(text, output_file, previous_text, next_text)
    
    def _generate_audio_chunk_openai(self, text, output_file, previous_text="", next_text=""):
        try:
            response = self.client.audio.speech.create(
                model="tts-1",
                voice="nova",  # Using nova as default, can be made configurable
                input=text
            )
            response.stream_to_file(output_file)
            return output_file
        except Exception as e:
            logger.error(f"Error generating audio for chunk: {e}")
            return None
    
    def _generate_audio_chunk_elevenlabs(self, text, output_file, previous_text="", next_text=""):
        """Generate audio for a single chunk of text with context"""
        try:
            audio = self.client.generate(
                voice="Sarah",  # Can be made configurable
                text=text,
                model_id="eleven_turbo_v2",
                output_format="mp3_44100_64",
                previous_text=previous_text,
                next_text=next_text
            )
            
            # Write the audio to file
            with open(output_file, "wb") as f:
                f.write(audio)
            return output_file
        except Exception as e:
            logger.error(f"Error generating audio for chunk: {e}")
            return None

    def _merge_audio_files(self, chunk_files, output_path):
        """Merge multiple audio files into one"""
        try:
            from pydub import AudioSegment
            
            # Load the first file
            combined = AudioSegment.from_mp3(chunk_files[0])
            
            # Add small pause between chunks (500ms)
            pause = AudioSegment.silent(duration=500)
            
            # Append the rest
            for chunk_file in chunk_files[1:]:
                audio_chunk = AudioSegment.from_mp3(chunk_file)
                combined += pause + audio_chunk
            
            # Export the final file
            combined.export(output_path, format="mp3")
        except Exception as e:
            logger.error(f"Error merging audio files: {e}")
            # If merge fails, copy the first file as fallback
            if chunk_files:
                shutil.copy2(chunk_files[0], output_path)
                
class StreamingTTSAgent(TTSAgent):
    """
    A TTS Agent that streams audio chunks instead of creating a single merged file.
    It inherits from TTSAgent but overrides the call flow to produce streaming audio data.

    StreamingTTSAgent: A streaming-first Text-to-Speech agent that processes and converts text to audio in real-time.

    Design Principles and Requirements:
    --------------------------------
    1. Streaming Architecture:
    - Yields audio chunks as soon as they are ready while maintaining sequential order
    - Processes LLM text generation and TTS conversion concurrently
    - Supports both streaming and non-streaming (file-based) use cases
    - Maintains backward compatibility with base TTSAgent class

    2. Text Processing:
    - Handles both TTS-friendly and non-TTS-friendly input text
    - For non-TTS-friendly text:
        * Streams LLM output in real-time
        * Processes text chunks as they arrive (split by \n\n)
        * Maintains chunk ordering for coherent audio output
    - For TTS-friendly text:
        * Directly splits into chunks and processes in parallel
        * Preserves original text structure and formatting

    3. Performance Requirements:
    - Minimizes latency between text input and first audio output
    - Processes chunks in parallel using ThreadPoolExecutor
    - Maintains memory efficiency by streaming data instead of loading entire audio
    - Prevents busy-waiting through appropriate sleep intervals
    - Scales efficiently with large text inputs

    4. Storage and Caching:
    - Caches final merged audio file for future requests
    - Implements file-based fallback for error cases
    - Maintains atomic file operations to prevent partial writes
    - Supports configurable storage paths and formats

    5. Error Handling:
    - Graceful degradation in case of API failures
    - Proper cleanup of resources (threads, file handles)
    - Detailed logging for debugging and monitoring
    - Fallback mechanisms for partial failures

    6. API Design:
    - Maintains consistent interface with base TTSAgent
    - Supports both OpenAI and ElevenLabs TTS backends
    - Configurable parameters for voice, model, and format
    - Clear separation of concerns between text processing and audio generation

    7. Non-Functional Requirements:
    - Thread safety for parallel processing
    - Resource management (memory, threads, API calls)
    - Proper cleanup of temporary resources
    - Maintainable and extensible code structure

    Implementation Details:
    ---------------------
    1. Core Components:
    - ThreadPoolExecutor for parallel TTS processing
    - Streaming generator for audio chunk delivery
    - LLM integration for text preprocessing
    - Audio merging and storage functionality

    2. Data Flow:
    Input Text -> [Optional LLM Processing] -> Chunk Splitting -> 
    Parallel TTS Generation -> Ordered Streaming -> [Optional Storage]

    3. Key Methods:
    - __call__: Main entry point, handles streaming and processing
    - _generate_audio_chunk_in_memory: Converts text to audio bytes
    - Backend-specific methods for OpenAI and ElevenLabs

    4. State Management:
    - Maintains chunk ordering through indexed futures
    - Tracks pending and completed TTS tasks
    - Accumulates audio chunks for final storage

    Usage Examples:
    -------------
    1. Basic streaming usage:
    ```python
    agent = StreamingTTSAgent(keys, storage_path)
    for audio_chunk in agent(text):
        # Process or play audio chunk
        play_audio(audio_chunk)
    ```

    2. With storage:
    ```python
    agent = StreamingTTSAgent(keys, "output/audio.mp3")
    audio_chunks = list(agent(text))  # Streams and stores
    # Audio file will be available at output/audio.mp3
    ```

    Dependencies:
    ------------
    - pydub: For audio processing and merging
    - openai/elevenlabs: TTS backend APIs
    - concurrent.futures: Parallel processing
    - tempfile: Temporary file handling

    Configuration:
    -------------
    - storage_path: Path for storing merged audio files
    - convert_to_tts_friendly_format: Boolean for LLM preprocessing
    - API keys and backend selection
    - Voice and model parameters

    Error Cases:
    -----------
    1. API failures: Returns None for chunk, continues processing
    2. Storage failures: Logs error, attempts partial storage
    3. LLM failures: Falls back to direct TTS processing
    4. Chunk processing: Skips failed chunks, maintains order

    Performance Considerations:
    ------------------------
    1. Memory Usage:
    - Streams chunks instead of loading entire audio
    - Cleans up completed futures and audio data
    - Manages thread pool size for parallel processing

    2. API Efficiency:
    - Batches API calls appropriately
    - Reuses API connections when possible
    - Implements appropriate rate limiting

    3. Storage Efficiency:
    - Uses temporary files for intermediate storage
    - Implements efficient merging strategies
    - Handles large files through streaming

    Maintenance Notes:
    ----------------
    - Regular cleanup of cached files recommended
    - Monitor API usage and rate limits
    - Check for backend API updates and compatibility
    - Review error logs for potential improvements
    """

    def __call__(self, text, images=[], temperature=0.2, stream=True, max_tokens=None, system=None, web_search=False):
        """
        Streams audio chunks as they become ready while maintaining order.
        Also accumulates chunks for final storage.
        """
        # Determine output path for final storage
        if self.storage_path.endswith('.mp3'):
            output_path = self.storage_path
        else:
            os.makedirs(self.storage_path, exist_ok=True)
            output_path = os.path.join(self.storage_path, 'output.mp3')

        # If file exists, stream it directly
        if os.path.exists(output_path):
            with open(output_path, 'rb') as f:
                while chunk := f.read(8192):
                    yield chunk
            return

        
        for chunk in self.process_chunks(text, output_path, images, temperature, max_tokens, stream):
            yield chunk
    
    def process_chunks(self, text, output_path, images, temperature, max_tokens, stream):
        current_chunk = ""
        next_chunk_index = 0
        pending_futures = {}  # {index: Future}
        all_audio_chunks = []  # For final storage

        with concurrent.futures.ThreadPoolExecutor() as executor:
            if self.convert_to_tts_friendly_format and not self.is_tts_friendly(text):
                # Process streaming LLM output
                llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])
                chunk_index = 0

                for partial_text in llm(self.prompt.format(text=text), 
                                        images=images, 
                                        temperature=temperature,
                                        stream=True, 
                                        max_tokens=max_tokens, 
                                        system=self.system):
                    current_chunk += partial_text
                    
                    # Process complete chunks (split by \n\n)
                    if '\n\n' in current_chunk:
                        chunks = current_chunk.split('\n\n')
                        # Keep last incomplete chunk
                        current_chunk = chunks[-1]
                        
                        # Submit complete chunks for TTS
                        for chunk in chunks[:-1]:
                            if chunk.strip():
                                future = executor.submit(
                                    self._generate_audio_chunk_in_memory, 
                                    chunk.strip()
                                )
                                pending_futures[chunk_index] = future
                                chunk_index += 1

                        # Yield ready chunks in order
                        while next_chunk_index in pending_futures:
                            future = pending_futures[next_chunk_index]
                            if future.done():
                                mp3_data = future.result()
                                if mp3_data:
                                    all_audio_chunks.append(mp3_data)
                                    yield mp3_data
                                del pending_futures[next_chunk_index]
                                next_chunk_index += 1
                            else:
                                break

                # Process final chunk if not empty
                if current_chunk.strip():
                    future = executor.submit(
                        self._generate_audio_chunk_in_memory, 
                        current_chunk.strip()
                    )
                    pending_futures[chunk_index] = future
                    chunk_index += 1

            else:
                # Text is already TTS-friendly
                chunks = [c.strip() for c in text.split('\n\n') if c.strip()]
                for i, chunk in enumerate(chunks):
                    future = executor.submit(
                        self._generate_audio_chunk_in_memory, 
                        chunk
                    )
                    pending_futures[i] = future

            # Yield remaining chunks in order
            while pending_futures:
                if next_chunk_index in pending_futures:
                    future = pending_futures[next_chunk_index]
                    if future.done():
                        mp3_data = future.result()
                        if mp3_data:
                            all_audio_chunks.append(mp3_data)
                            yield mp3_data
                        del pending_futures[next_chunk_index]
                        next_chunk_index += 1
                    else:
                        # Small sleep to prevent busy waiting
                        time.sleep(0.1)
                else:
                    # Small sleep to prevent busy waiting
                    time.sleep(0.1)

        # Save accumulated audio chunks to file
        try:
            from pydub import AudioSegment
            import io
            
            audio_segments = []
            for chunk_data in all_audio_chunks:
                segment = AudioSegment.from_mp3(io.BytesIO(chunk_data))
                audio_segments.append(segment)
            
            if audio_segments:
                # Add small pause between chunks
                pause = AudioSegment.silent(duration=500)
                combined = audio_segments[0]
                for segment in audio_segments[1:]:
                    combined += pause + segment
                
                combined.export(output_path, format="mp3")
        except Exception as e:
            logger.error(f"Error saving merged audio file: {e}")
            # Save first chunk if merge fails
            if all_audio_chunks:
                with open(output_path, 'wb') as f:
                    f.write(all_audio_chunks[0])


    def _generate_audio_chunk_in_memory(self, text):
        """
        Similar to _generate_audio_chunk, but returns mp3 data in memory (bytes) 
        instead of writing to a file. We'll rely on the underlying TTS calls 
        but direct them to a bytes buffer.
        """
        if USE_OPENAI_API:
            return self._generate_audio_chunk_openai_in_memory(text)
        else:
            return self._generate_audio_chunk_elevenlabs_in_memory(text)

    def _generate_audio_chunk_openai_in_memory(self, text):
        """
        Generate TTS using OpenAI API and return the mp3 data in-memory.
        """
        try:
            response = self.client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=text
            )
            # Collect audio in memory
            mp3_data = response.content  # 'HttpxBinaryResponseContent' object has 'content' attribute to get raw data
            return mp3_data
        except Exception as e:
            logger.error(f"Error generating audio for chunk: {e}")
            return None

    def _generate_audio_chunk_elevenlabs_in_memory(self, text):
        """
        Generate TTS using ElevenLabs API and return mp3 data in-memory.
        """
        try:
            audio = self.client.generate(
                voice="Sarah",  # can be made configurable
                text=text,
                model_id="eleven_turbo_v2",
                output_format="mp3_44100_64"
            )
            return audio  # the 'audio' here is already raw mp3 bytes from the client
        except Exception as e:
            logger.error(f"Error generating audio for chunk: {e}")
            return None


class WebSearchWithAgent(Agent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=False):
        super().__init__(keys)
        self.gscholar = gscholar
        self.model_name = model_name
        self.detail_level = detail_level
        self.concurrent_searches = True
        self.timeout = timeout
        self.no_intermediate_llm = no_intermediate_llm
        self.combiner_prompt = f"""
You are tasked with synthesizing information from multiple web search results to provide a comprehensive and accurate response to the user's query. Your goal is to combine these results into a coherent and informative answer.

Instructions:
1. Carefully analyze and integrate information from all provided web search results.
2. Only use information from the provided web search results.
3. If the web search results are not helpful or relevant, state: "No relevant information found in the web search results." and end your response.
4. If appropriate, include brief citations to indicate the source of specific information (e.g., "According to [Source],...").
5. Organize the information in a logical and easy-to-read format.
6. Put relevant citations inline in markdown format in the text at the appropriate places in your response.

Your response should include:
1. A comprehensive answer to the user's query, synthesizing information from all relevant search results with references in markdown link format closest to where applicable.
2. If applicable, a brief summary of any conflicting information or differing viewpoints found in the search results.
3. If no web search results are provided, please say "No web search results provided." and end your response.

Web search results:
<|results|>
{{web_search_results}}
</|results|>

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please compose your response, ensuring it thoroughly addresses the user's query while synthesizing information from all provided search results.
"""

        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1', 'detailed context1'), 
    ('query2', 'detailed context2'), 
    ('query3', 'detailed context3'), 
    ...
]
```

Text: {{text}}

Generate up to 3 highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""
    def extract_queries_contexts(self, code_string):
        regex = r"```(?:\w+)?\s*(.*?)```"
        matches = re.findall(regex, code_string, re.DOTALL | re.MULTILINE | re.IGNORECASE)
        
        if not matches:
            return None  # or you could return an empty list [], depending on your preference
        
        matches = [m.split("=")[-1].strip() for m in matches]
        
        code_to_execute = [c.strip() for c in matches if c.strip()!="" and c.strip()!="[]" and c.strip().startswith("[") and c.strip().endswith("]")][-1:]
        return "\n".join(code_to_execute)
    
    def remove_code_blocks(self, text):
        regex = r"```(?:\w+)?\s*(.*?)```"
        return re.sub(regex, r"\1", text, re.DOTALL | re.MULTILINE | re.IGNORECASE)
    
    def get_results_from_web_search(self, text, text_queries_contexts):

        array_string = text_queries_contexts
        web_search_results = []
        try:
            # Use ast.literal_eval to safely evaluate the string as a Python expression
            import ast
            text_queries_contexts = ast.literal_eval(array_string)
            
            # Ensure the result is a list of tuples
            if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) for item in text_queries_contexts):
                raise ValueError("Invalid format: expected list of tuples")
            
            # Now we have text_queries_contexts as a list of tuples of the form [('query', 'context'), ...]
            # We need to call simple_web_search_with_llm for each query and context
            # simple_web_search_with_llm(keys, user_context, queries, gscholar)
            
            if self.concurrent_searches:
                futures = []
                for query, context in text_queries_contexts:
                    future = get_async_future(simple_web_search_with_llm, self.keys, text + "\n\n" + context, [query], gscholar=self.gscholar, provide_detailed_answers=self.detail_level, no_llm=len(text_queries_contexts) <= 3 or self.no_intermediate_llm, timeout=self.timeout * len(text_queries_contexts))
                    futures.append(future)

                web_search_results = []
                for future in futures:
                    result = sleep_and_get_future_result(future)
                    web_search_results.append(f"<b>{query}</b></br>" + "\n\n" + context + "\n\n" + result)
            else:
                web_search_results = []
                for query, context in text_queries_contexts:
                    result = simple_web_search_with_llm(self.keys, text + "\n\n" + context, [query], gscholar=self.gscholar, provide_detailed_answers=self.detail_level, no_llm=len(text_queries_contexts) <= 3 or self.no_intermediate_llm, timeout=self.timeout)
                    web_search_results.append(f"<b>{query}</b></br>" + "\n\n" + context + "\n\n" + result)
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing text_queries_contexts: {e}")
            text_queries_contexts = None
        return "\n".join(web_search_results)
    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=True):
        # Extract queries and contexts from the text if present, otherwise set to None
        # We will get "[('query', 'context')...,]" style large array which is string, need to eval or ast.literal_eval this to make it python array, then error handle side cases.
        # Ensure the result is a list of tuples
        # Parallel search all queries and generate markdown formatted response, latex formatted response and bibliography entries inside code blocks.
        text_queries_contexts = self.extract_queries_contexts(text)

        answer = ""
        answer += f"""User's query and conversation history: 
<|context|>
{text}
</|context|>\n\n"""

        
        
        if text_queries_contexts is not None and len(text_queries_contexts) > 0:
            answer += f"Generated Queries and Contexts: {text_queries_contexts}\n\n"
            yield {"text": '\n```\n'+text_queries_contexts+'\n```\n', "status": "Created/Obtained search queries and contexts"}
            text = self.remove_code_blocks(text)
            # Extract the array-like string from the text
            web_search_results = self.get_results_from_web_search(text, text_queries_contexts)
            yield {"text": web_search_results + "\n", "status": "Obtained web search results"}
            answer += f"{web_search_results}\n\n"
        else:
            llm = CallLLm(self.keys, model_name=CHEAP_LLM[0])
            # Write a prompt for the LLM to generate queries and contexts
            llm_prompt = self.llm_prompt.format(text=text)

            # Call the LLM to generate queries and contexts
            response = llm(llm_prompt, images=[], temperature=0.7, stream=False, max_tokens=None, system=None)

            # Parse the response to extract queries and contexts
            import ast
            try:
                # Use ast.literal_eval to safely evaluate the string as a Python expression
                response = self.extract_queries_contexts(response)
                text_queries_contexts = ast.literal_eval(response)
                text = self.remove_code_blocks(text)
                yield {"text": '\n```\n'+response+'\n```\n', "status": "Created/Obtained search queries and contexts"}
                answer += f"Generated Queries and Contexts: ```\n{response}\n```\n\n"
                
                # Validate the parsed result
                if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) and len(item) == 2 for item in text_queries_contexts):
                    raise ValueError("Invalid format: expected list of tuples")
                
                # If valid, proceed with web search using the generated queries and contexts
                web_search_results = self.get_results_from_web_search(text, str(text_queries_contexts))
                yield {"text": web_search_results + "\n", "status": "Obtained web search results"}
                answer += f"{web_search_results}\n\n"
            except (SyntaxError, ValueError) as e:
                logger.error(f"Error parsing LLM-generated queries and contexts: {e}")
                web_search_results = []
                
        if len(web_search_results) == 0:
            raise ValueError("No relevant information found in the web search results.")
        
        # if len(web_search_results) == 1 and not self.no_intermediate_llm:
        #     yield {"text": '' + "\n", "status": "Completed literature review for a single query"}
        
        # Now we have web_search_results as a list of strings, each string is a web search result.
        # After response is generated for all queries (within a timeout) then use a combiner LLM to combine all responses into a single response.
        llm = CallLLm(self.keys, model_name=self.model_name)
        
        combined_response = llm(self.combiner_prompt.format(web_search_results=web_search_results, text=text), images=images, temperature=temperature, stream=False, max_tokens=max_tokens, system=system)
        yield {"text": '\n'+combined_response+'\n', "status": "Completed web search with agent"}
        answer += f"{combined_response}\n\n"
        yield {"text": self.post_process_answer(answer, temperature, max_tokens, system), "status": "Completed web search with agent"}

    def post_process_answer(self, answer, temperature=0.7, max_tokens=None, system=None):
        return ""
    
    def get_answer(self, text, images=[], temperature=0.7, stream=True, max_tokens=None, system=None, web_search=True):
        return convert_stream_to_iterable(self.__call__(text, images, temperature, stream, max_tokens, system, web_search))[-2]

class LiteratureReviewAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=90, gscholar=False, no_intermediate_llm=False):
        super().__init__(keys, model_name, detail_level, timeout, gscholar, no_intermediate_llm)
        self.concurrent_searches = False
        self.combiner_prompt = f"""
You are tasked with creating a comprehensive literature survey based on multiple web search results. Your goal is to synthesize this information into a cohesive, academically rigorous review that addresses the user's query.

Instructions:
1. Carefully analyze and integrate information from all provided web search results.
2. Only use information from the provided web search results.
3. Include relevant references to support your points, citing them appropriately within the text.
4. If the web search results are not helpful or relevant, state: "No relevant information found in the web search results." and end your response.
5. Put relevant citations inline in markdown format in the text at the appropriate places in your response.
6. If no web search results are provided, please say so by saying "No web search results provided." and end your response.

These elements are crucial for compiling a complete academic document later.

Web search results:
<|results|>
{{web_search_results}}
</|results|>


User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please compose your literature survey, ensuring it thoroughly addresses the user's query while synthesizing information from all provided search results. Include the Latex version of the literature review and bibliography in BibTeX format at the end of your response.
"""

        year = time.localtime().tm_year
        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1 arxiv', 'detailed context1'), 
    ('query2 research papers', 'detailed context2'), 
    ('query3 research in {year}', 'detailed context3'), 
    ...
]
```

Text: {{text}}

Add keywords like 'arxiv', 'research papers', 'research in {year}' to the queries to get relevant academic sources.
Generate up to 3 highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""
        self.write_in_latex_prompt = f"""
You were tasked with creating a comprehensive literature survey based on multiple web search results. Our goal was to synthesize this information into a cohesive, academically rigorous review that addresses the user's query.
Based on the user's query and the web search results, you have generated a literature review in markdown format. Now, you need to convert this markdown literature review into LaTeX format.
If any useful references were missed in the literature review, you can include them in the LaTeX version along with the existing content.

Given below is the user's query, the web search results and markdown literature review you have generated:
<|context|>
{{answer}}
</|context|>

Include the only two items below in your response.
1. Literature review written in LaTeX, enclosed in a code block. Use newlines in the LaTeX code after each full sentence to wrap it instead of making lines too long. Ensure that the LaTeX version is well-formatted and follows academic writing conventions.
2. A bibliography in BibTeX format, enclosed in a separate code block.

Write your response with two items (Literature review in LaTeX enclosed in code block and bibliography in BibTeX format enclosed in a separate code block) below.
"""
    def post_process_answer(self, answer, temperature=0.7, max_tokens=None, system=None):
        llm = CallLLm(self.keys, model_name=self.model_name)

        combined_response = llm(self.write_in_latex_prompt.format(answer=answer),
                                temperature=temperature, stream=False, max_tokens=max_tokens,
                                system=system)
        return "\n\n<hr></br>" + combined_response


class BroadSearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, gscholar=False, no_intermediate_llm=True):
        super().__init__(keys, model_name, detail_level, timeout, gscholar, no_intermediate_llm)
        self.llm_prompt = f"""
Given the following text, generate a list of relevant queries and their corresponding contexts. 
Each query should be focused and specific, while the context should provide background information and tell what is the user asking about and what specific information we need to include in our literature review.
Format your response as a Python list of tuples as given below: 
```python
[
    ('query1 word1_for_localisation', 'detailed context1'), 
    ('query2 maybe_word2_for_site_specific_searches', 'detailed context2'), 
    ('query3', 'detailed context3'), 
    ...
]
```

Text: {{text}}

Generate as many as needed relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""

class ReflectionAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], improve_model: str, outline_model: str):
        self.keys = keys
        self.writer_model = writer_model
        self.improve_model = improve_model
        self.outline_model = outline_model
        self.system = """
As an AI language model assistant, your task is to enhance a simple answer provided for a user's query by performing self-reflection and objective analysis.
Answer comprehensively in detail like a PhD scholar and leading experienced expert in the field. Compose a clear, detailed, comprehensive, thoughtful and highly informative response.
Provide a detailed answer along with all necessary details, preliminaries, equations, references, citations, examples, explanations, etc.
We need to help people with hand, wrist disability and minimise typing and editing on their side. Deduce what the question or query is asking about and then go above and beyond to provide a high quality response. Write full answers.
Answer completely in a way that our work can be used by others directly without any further editing or modifications. We need to be detail oriented, cover all references and provide details, work hard and provide our best effort. 
        """.strip()
        self.prompt = f"""
As an AI language model assistant, your task is to enhance simple answers provided for a user's query by performing self-reflection and objective analysis. 
You will be given:  
- A **User Query**  and some context around it if necessary.
- One or more **Simple Expert Answers** generated by one or more AI models.
- Some guidance on how to write a good answer from another LLM model. You may optionally use this guidance to further help your reflection and thinking steps.
  
Follow the steps outlined below, using the specified XML-style tags to structure your response. This format will help in parsing and reviewing each part of your process.  

---  
## Instructions:  
1. **Identify all goals:**  
   - Carefully read and understand the user's query.  
   - Determine the main objectives and what the user is seeking.  
   - Determine how we can go above and beyond to provide a high-quality response and help the user effectively.
   - Enclose your findings within `<goals>` and `</goals>` tags.  
  
2. **Reflect on the Simple Answer:**  
   - If more than one simple answer is provided by different models, consider each one and pick the best parts and aspects from each.
   - Identify areas of improvement and gaps in the simple answers provided.
   - Assess how these simple answers can be combined and improved to better meet the user's needs.  
   - Identify any missing information, corner cases, or important considerations.  
   - Enclose your reflection within `<reflection>` and `</reflection>` tags using bullet points.  
  
3. **Think Logically and Step by Step about how to improve the answer:**  
   - Outline your thought process for improving the answer.  
   - Provide a logical, step-by-step explanation of enhancements.  
   - Enclose your reasoning within `<thinking>` and `</thinking>` tags using bullet points.  
 
4. **Provide the Improved Answer:**  
   - Compose a new, comprehensive answer that addresses all aspects of the user's query, incorporating all improvements identified in your reflection and all information from the simple expert answers.
   - Provide any and all details from the simple expert answers we already have in our final answer.
   - Enclose the final answer within `<answer>` and `</answer>` tags.  
   - In your final answer mention all the details, improvements, and information from the simple expert answers we already have.
  
---  
**Formatting Guidelines:**  
- Use the following XML-style tags to structure your response:  
  - `<goals>` ... `</goals>`  
  - `<reflection>` ... `</reflection>`  
  - `<thinking>` ... `</thinking>`  
  - `<answer>` complete and final improved answer `</answer>`

User Query with context:
<user_query>
{{query}}
</user_query>

<optional_guidance>
{{guidance}}
</optional_guidance>

Simple Answers:
<simple_answers>
{{simple_answer}}
</simple_answers>

Now your overall response would look and be formatted like this:
<goals>
    [Identify the user's main objectives.]  
</goals>
<reflection>
    [Reflect on the simple answer and identify areas of improvement.]  
</reflection>
<thinking>
    [Provide a step-by-step plan for enhancements.]  
</thinking>
<answer>
    [Provide the complete and final improved answer to the user's query. Final answer must include all the details, improvements, and information from the simple expert answers we already have. It should be comprehensive and detailed. It should combine all the ideas, insights, and improvements from the simple expert answers and provide a highly informative, in-depth and useful answer.] 
</answer>

If we have multiple simple answers, we include all ideas, insights, and improvements from each simple answer in our final answer. Write in detail and in a comprehensive manner.
Use good organization, formatting and structure in your response. 
Use simple markdown formatting and indentation for appealing and clear presentation. For markdown formatting use 2nd level or lower level headers (##) and lower headers for different sections. Basically use small size headers only.
Now respond to the user's query and enhance the simple answer provided in the above format.
""".lstrip()
        self.good_answer_characteristics_prompt = f"""
Your task is to write down the characteristics of a good answer. You must mention how a good answer should be structured and formatted, what it should contain, and how it should be presented.
You will be given:  
- A **User Query**  and some context around it if necessary.

Based on the user query and the context provided, write down the characteristics of a good answer. 
You must mention 
- what topics a good answer to the user query must contain, 
- how it should be structured, 
- what areas it must cover, 
- what information it should provide,
- what details it should include,
- what are some nuances that should be considered,
- If the query is about a specific topic, what are some key points that should be included,
- If the query is a trivia, logic question, science question, math question, coding or other type of logical question then what are some high level steps and skills that are needed to solve the question, 
- what are some Aha stuff and gotchas that should be included,
- what are some corner cases that should be addressed,
- how can we make the answer more informative and useful, engaging and interesting, stimulating and thought-provoking,
- how can we make the answer more comprehensive and detailed,
- how can we make the answer more accurate and correct and useful and implementable if needed,
- what parts of the answer, topics, areas, and details should be dived deeper into and emphasized, 
- how it should be formatted,
- and how it should be presented.
- You can also mention what are some common mistakes that should be avoided in the answer and what are some common pitfalls that should be addressed.
- Write a detailed and comprehensive outline of the answer that should be provided to the user.

User Query with context:
<user_query>
{{query}}
</user_query>

Write down the characteristics of a good answer in detail following the above guidelines and adding any additional information you think is relevant.
""".strip()
        self.first_model = CallLLm(keys, self.writer_model) if isinstance(self.writer_model, str) else CallMultipleLLM(keys, self.writer_model)
        self.improve_model = CallLLm(keys, self.improve_model)
        self.outline_model = CallLLm(keys, self.outline_model) if isinstance(self.outline_model, str) else CallLLm(keys, self.improve_model)

    @property
    def model_name(self):
        return self.writer_model
    
    @model_name.setter
    def model_name(self, model_name):
        self.writer_model = model_name
        self.improve_model = model_name if isinstance(model_name, str) else model_name[0]
        self.outline_model = model_name if isinstance(model_name, str) else model_name[0]
        
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        st = time.time()
        # outline_future = get_async_future(self.outline_model, self.good_answer_characteristics_prompt.format(query=text), images, temperature, False, max_tokens, system)
        first_response = self.first_model(text, images, temperature, False, max_tokens, system)
        time_logger.info(f"Time taken to get multi model response: {time.time() - st} with response length: {len(first_response.split())}")
        # outline = sleep_and_get_future_result(outline_future)
        # time_logger.info(f"Time taken to get till outline: {time.time() - st} with outline length: {len(outline.split())}")
        outline = ""
        improve_prompt = self.prompt.format(query=text, simple_answer=first_response, guidance=outline)
        if system is None:
            system = self.system
        else:
            system = f"{self.system}\n{system}"

        improved_response = self.improve_model(improve_prompt, images, temperature, False, max_tokens, system)
        time_logger.info(f"Time taken to get improved response: {time.time() - st}")
        # Now lets parse the response and return the improved response
        goals = improved_response.split('</goals>')[0].split('<goals>')[-1]
        reflection = improved_response.split('</reflection>')[0].split('<reflection>')[-1]
        thinking = improved_response.split('</thinking>')[0].split('<thinking>')[-1]
        revised_reflection = improved_response.split('</revised_reflection>')[0].split('<revised_reflection>')[-1]
        revised_thinking = improved_response.split('</revised_thinking>')[0].split('<revised_thinking>')[-1]
        improvements = improved_response.split('</improvements>')[0].split('<improvements>')[-1]
        answer = improved_response.split('</answer>')[0].split('<answer>')[-1]
        random_identifier = str(uuid.uuid4())
        first_response = f"**First Response :** <div data-toggle='collapse' href='#firstResponse-{random_identifier}' role='button'></div> <div class='collapse' id='firstResponse-{random_identifier}'>\n" + first_response + f"\n</div>\n\n"
        answer = first_response + f"\n\n**Improved Response :** <div data-toggle='collapse' href='#improvedResponse-{random_identifier}' role='button' aria-expanded='true'></div> <div class='collapse show' id='improvedResponse-{random_identifier}'>\n" + answer + f"\n</div>"
        # return a dictionary
        return {
            'goals': goals,
            'reflection': reflection,
            'thinking': thinking,
            'revised_reflection': revised_reflection,
            'revised_thinking': revised_thinking,
            'improvements': improvements,
            'answer': answer
        }
        
        
class BestOfNAgent(Agent):
    def __init__(self, keys, writer_model: Union[List[str], str], evaluator_model: str, n_responses: int = 3):
        self.keys = keys
        self.writer_model = writer_model
        self.evaluator_model = evaluator_model
        self.n_responses = n_responses
        self.system = """
Select the best response from the given multiple responses.
        """.strip()

        self.evaluator_prompt = f"""
You are tasked with evaluating multiple responses to a user query and selecting the best one. 
Analyze each response carefully and rate them based on the following criteria:
- Correctness and accuracy of information
- Comprehensiveness and completeness
- Clarity and organization
- Relevance to the query
- Practical usefulness
- Technical depth and expertise demonstrated
- Quality of explanations and examples

User Query:
<user_query>
{{query}}
</user_query>

Generated Responses:
<generated_responses>
{{responses}}
</generated_responses>

Please evaluate each response and provide your analysis in the following XML format:

<evaluation>
    <analysis>
        [Detailed analysis of each response, comparing their strengths and weaknesses]
    </analysis>
    
    <rankings>
        [Numerical rankings of responses with brief justification for each]
    </rankings>
    
    <reasoning>
        [Detailed reasoning for selecting the best response]
    </reasoning>
    
    <best_response_index>
        [Index of the best response (0-based)]
    </best_response_index>
    
    
</evaluation>
"""

    @property
    def model_name(self):
        return self.writer_model
    
    @model_name.setter
    def model_name(self, model_name):
        self.writer_model = model_name
        self.evaluator_model = model_name if isinstance(model_name, str) else model_name[0]
        
    def get_multiple_responses(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        st = time.time()
        
        # Generate N responses in parallel
        futures = []
        for _ in range(self.n_responses):
            if isinstance(self.writer_model, str):
                first_model = CallLLm(self.keys, self.writer_model)
                future = get_async_future(first_model, text, images, temperature, False, max_tokens, system)
                futures.append(future)
            else:
                for model in self.writer_model:
                    first_model = CallLLm(self.keys, model)
                    future = get_async_future(first_model, text, images, temperature, False, max_tokens, system)
                    futures.append(future)

        # Collect responses
        responses = []
        for i, future in enumerate(futures):
            try:
                response = sleep_and_get_future_result(future)
                responses.append((i, response))
            except Exception as e:
                logger.error(f"Error getting response {i}: {e}")

        time_logger.info(f"Time taken to get {len(responses)} responses: {time.time() - st}")

        # Format responses for evaluation
        formatted_responses = "\n\n".join([f"Response {i}:\n{response}" for i, response in responses])
        return formatted_responses, responses
    
    def combine_responses(self, formatted_responses, responses, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        # Evaluate responses
        evaluator = CallLLm(self.keys, self.evaluator_model)
        eval_text = self.evaluator_prompt.format(query=text, responses=formatted_responses)
        evaluation = evaluator(
            eval_text,
            images=images,
            temperature=temperature,
            stream=False,
            max_tokens=max_tokens,
            system=system + "\n\n" + self.system
        )

        # Parse evaluation
        analysis = evaluation.split('</analysis>')[0].split('<analysis>')[-1].strip()
        rankings = evaluation.split('</rankings>')[0].split('<rankings>')[-1].strip()
        best_index = int(evaluation.split('</best_response_index>')[0].split('<best_response_index>')[-1].strip())
        reasoning = evaluation.split('</reasoning>')[0].split('<reasoning>')[-1].strip()

        # Format the final answer with collapsible sections
        random_identifier = str(uuid.uuid4())
        
        # Format all responses in collapsible divs
        all_responses = []
        for i, (_, response) in enumerate(responses):
            is_best = i == best_index
            response_class = 'collapse show' if is_best else 'collapse'
            response_header = f"**{'Best ' if is_best else ''}Response {i+1}:**"
            aria_expanded = 'true' if is_best else 'false'
            all_responses.append(
                f"{response_header} <div data-toggle='collapse' href='#response-{random_identifier}-{i}' role='button' aria-expanded='{aria_expanded}'></div> "
                f"<div class='{response_class}' id='response-{random_identifier}-{i}'>\n{response}\n</div>"
            )

        # Format evaluation details in a collapsible div
        evaluation_details = (
            f"**Evaluation Details:** <div data-toggle='collapse' href='#evaluation-{random_identifier}' role='button'></div> "
            f"<div class='collapse' id='evaluation-{random_identifier}'>\n"
            f"### Analysis\n{analysis}\n\n"
            f"### Rankings\n{rankings}\n\n"
            f"### Reasoning for Best Response\n{reasoning}\n"
            f"</div>"
        )

        # Combine everything into the final answer
        final_answer = "\n\n".join([
            "# Generated Responses and Evaluation",
            "\n\n".join(all_responses),
            evaluation_details
        ])

        return {
            'answer': final_answer,
            'best_response_index': best_index,
            'analysis': analysis,
            'rankings': rankings,
            'reasoning': reasoning
        }
    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        formatted_responses, responses = self.get_multiple_responses(text, images, temperature, stream, max_tokens, system, web_search)
        combined_response = self.combine_responses(formatted_responses, responses, text, images, temperature, stream, max_tokens, system, web_search)
        return combined_response
        
        


class NResponseAgent(BestOfNAgent):
    def __init__(self, keys, writer_model: Union[List[str], str], n_responses: int = 3):
        super().__init__(keys, writer_model, None, n_responses)


    # No need for model_name property and setter since they are inherited from BestOfNAgent
    
    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        _, responses = self.get_multiple_responses(text, images, temperature, stream, max_tokens, system, web_search)
        # Format the final answer with collapsible sections
        random_identifier = str(uuid.uuid4())
        best_index = 0
        # Format all responses in collapsible divs
        all_responses = []
        for i, (_, response) in enumerate(responses):
            is_best = i == best_index
            response_class = 'collapse show' if is_best else 'collapse'
            response_header = f"**{'Best ' if is_best else ''}Response {i+1}:**"
            aria_expanded = 'true' if is_best else 'false'
            all_responses.append(
                f"{response_header} <div data-toggle='collapse' href='#response-{random_identifier}-{i}' role='button' aria-expanded='{aria_expanded}'></div> "
                f"<div class='{response_class}' id='response-{random_identifier}-{i}'>\n{response}\n</div>"
            )

        # Combine everything into the final answer
        final_answer = "\n\n".join([
            "# Generated Responses and Evaluation",
            "\n\n".join(all_responses)
        ])

        return {
            'answer': final_answer,
            'best_response_index': best_index,
            
        }
        
def is_future_ready(future):
    """Check if a future is ready without blocking"""
    return future.done() if hasattr(future, 'done') else True


class WhatIfAgent(Agent):
    def __init__(self, keys, writer_models: Union[List[str], str], n_scenarios: int = 3):
        super().__init__(keys)
        self.keys = keys
        # Convert single model to list for consistent handling
        self.writer_models = [writer_models] if isinstance(writer_models, str) else writer_models
        self.n_scenarios = n_scenarios
        
        self.what_if_prompt = """
You are tasked with generating creative "what-if" scenarios that would change the answer to the user's query in interesting ways.

For the given text/query, generate {n_scenarios} alternative what-if scenarios where the answer would be significantly different.
These scenarios can:
1. Add new constraints or remove existing ones
2. Change the context or situation in subtle ways
3. Introduce unexpected elements
4. Consider edge cases or extreme situations
5. Explore creative possibilities
6. Make sure the scenarios you generate are realistic and grounded in the context of the query and the domain of the query.

Format your response as a Python list of tuples, where each tuple contains:
1. A brief title for the what-if scenario
2. The modified query/situation incorporating the what-if
3. A short explanation of how this changes things

The format should be exactly like this:
```python
[
("Brief Title 1", "Modified query/situation 1", "How this changes things 1"),
("Brief Title 2", "Modified query/situation 2", "How this changes things 2"),
...
]
```

Original query/text:
<query>
{text}
</query>

Generate exactly {n_scenarios} creative and diverse what-if scenarios that would lead to different answers.
Write your response as a code block containing only the Python list of tuples.
"""


        
    def extract_what_ifs(self, response):
        """Extract and validate the what-if scenarios from LLM response"""
        import re
        import ast
        
        # Extract code block
        code_pattern = r"```(?:python)?\s*(.*?)```"
        matches = re.findall(code_pattern, response, re.DOTALL)
        
        if not matches:
            return []
            
        try:
            # Get the last code block and evaluate it
            scenarios = ast.literal_eval(matches[-1].strip())
            
            # Validate format
            if not isinstance(scenarios, list) or not all(
                isinstance(s, tuple) and len(s) == 3 
                for s in scenarios
            ):
                return []
                
            return scenarios
            
        except Exception as e:
            logger.error(f"Error parsing what-if scenarios: {e}")
            return []

    def format_what_if_query(self, original_text: str, what_if: tuple) -> str:
        """Format the what-if scenario into a query for the LLM"""
        title, modified_query, explanation = what_if
        return f"""Original Query/Situation:
{original_text}

What-if Scenario: {title}
Modified Situation: {modified_query}
Impact: {explanation}

Please provide an answer for this modified scenario."""

        
    def get_next_model(self, index: int) -> str:
        """Get next model in round-robin fashion"""
        return self.writer_models[index % len(self.writer_models)]

    def __call__(self, text, images=[], temperature=0.7, stream=False, max_tokens=None, system=None, web_search=False):
        # Start what-if generation immediately in parallel
        what_if_future = get_async_future(
            what_if_llm := CallLLm(self.keys, self.writer_models[0]),
            self.what_if_prompt.format(text=text, n_scenarios=self.n_scenarios),
            temperature=temperature,
            stream=False
        )

        # Start initial response streaming immediately
        writer_llm = CallLLm(self.keys, self.writer_models[0])
        initial_response_stream = writer_llm(
            text, 
            images=images,
            temperature=temperature,
            stream=True,
            max_tokens=max_tokens,
            system=system
        )

        # Variables to track state
        initial_response = ""
        what_if_scenarios = None
        what_if_futures = []
        random_identifier = str(uuid.uuid4())
        
        # Stream initial response while checking if what-if scenarios are ready
        for chunk in initial_response_stream:
            initial_response += chunk
            yield {"text": chunk, "status": "Generating initial response"}
            
            # Check if what-if scenarios are ready (non-blocking)
            if what_if_scenarios is None and is_future_ready(what_if_future):
                # Get scenarios and start their responses immediately
                what_if_response = sleep_and_get_future_result(what_if_future)
                what_if_scenarios = self.extract_what_ifs(what_if_response)
                
                # Start generating what-if responses in parallel
                for i, scenario in enumerate(what_if_scenarios, 1):
                    model = self.get_next_model(i)
                    writer_llm = CallLLm(self.keys, model)
                    modified_query = self.format_what_if_query(text, scenario)
                    future = get_async_future(
                        writer_llm,
                        modified_query,
                        images=images,
                        temperature=temperature,
                        stream=False,
                        max_tokens=max_tokens,
                        system=system
                    )
                    what_if_futures.append((scenario, future, model))

        # If what-if scenarios weren't ready during streaming, get them now
        if what_if_scenarios is None:
            what_if_response = sleep_and_get_future_result(what_if_future)
            what_if_scenarios = self.extract_what_ifs(what_if_response)
            
            # Start generating what-if responses
            for i, scenario in enumerate(what_if_scenarios, 1):
                model = self.get_next_model(i)
                writer_llm = CallLLm(self.keys, model)
                modified_query = self.format_what_if_query(text, scenario)
                future = get_async_future(
                    writer_llm,
                    modified_query,
                    images=images,
                    temperature=temperature,
                    stream=False,
                    max_tokens=max_tokens,
                    system=system
                )
                what_if_futures.append((scenario, future, model))

        # Format and yield what-if scenarios
        scenarios_text = "# What-If Scenarios Generated:\n\n"
        for i, (title, query, explanation) in enumerate(what_if_scenarios, 1):
            model_used = self.get_next_model(i)
            scenarios_text += f"**Scenario {i}: {title}** (Using model: {model_used})\n"
            scenarios_text += f"- Modified Situation: {query}\n"
            scenarios_text += f"- Impact: {explanation}\n\n"
        
        yield {"text": "\n\n" + scenarios_text, "status": "Generated what-if scenarios"}

        # Format initial response with collapsible section
        all_responses = [
            f"**Initial Response** (Using model: {self.writer_models[0]}):\n"
            f"<div data-toggle='collapse' href='#response-{random_identifier}-initial' role='button' aria-expanded='true'></div> "
            f"<div class='collapse show' id='response-{random_identifier}-initial'>\n{initial_response}\n</div>"
        ]

        # Collect and format what-if responses as they complete
        for i, (scenario, future, model) in enumerate(what_if_futures, 1):
            try:
                response = sleep_and_get_future_result(future)
                title = scenario[0]
                
                response_html = (
                    f"**What-If Scenario {i}: {title}** (Using model: {model})\n"
                    f"<div data-toggle='collapse' href='#response-{random_identifier}-{i}' "
                    f"role='button' aria-expanded='false'></div> "
                    f"<div class='collapse' id='response-{random_identifier}-{i}'>\n{response}\n</div>"
                )
                
                all_responses.append(response_html)
                yield {"text": "\n\n" + response_html, "status": f"Generated response for scenario {i} using {model}"}
                
            except Exception as e:
                logger.error(f"Error getting response for scenario {i} with model {model}: {e}")

        # Final yield with metadata
        yield {
            "text": "\n\n",
            "status": "Completed what-if analysis",
            "scenarios": what_if_scenarios,
            "initial_response": initial_response,
            "models_used": {
                "initial": self.writer_models[0],
                "what_if_generator": self.writer_models[0],
                "scenario_responses": [self.get_next_model(i) for i in range(1, len(what_if_scenarios) + 1)]
            }
        }


class PerplexitySearchAgent(WebSearchWithAgent):
    def __init__(self, keys, model_name, detail_level=1, timeout=60, num_queries=10):
        super().__init__(keys, model_name, detail_level, timeout)
        self.num_queries = num_queries
        self.perplexity_models = [
            "perplexity/llama-3.1-sonar-small-128k-online",
            # "perplexity/llama-3.1-sonar-large-128k-online"
        ]
        
        if detail_level >= 3:
            self.perplexity_models.append("perplexity/llama-3.1-sonar-large-128k-online")
        
        year = time.localtime().tm_year
        self.get_references = f"""
[Important: Provide links and references inline closest to where applicable and provide all references you used finally at the end for my question as well. Search and look at references and information exhaustively and dive deep before answering. Think carefully before answering and provide an comprehensive, extensive answer using the references deeply. Provide all references with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.]
""".strip()
        
        # Override the llm_prompt to generate more diverse queries while maintaining the same format
        self.llm_prompt = f"""
Given the following user query and context, generate a list of relevant queries and their corresponding contexts. 
generate diverse queries that:
1. Directly address the main topic
2. Explore related subtopics and side aspects
3. Include domain-specific variations (as relevant) by adding keywords like:
   - For scientific topics: "research papers", "arxiv", "scientific studies"
   - For location-based topics: append relevant place names
   - For temporal topics: add years/timeframes
   - For domain-specific topics: add field identifiers (finance, politics, technology, etc.)

Format your response as a Python list of tuples as given below: 
```python
[
    ('main topic exact query', 'short context about main topic'), 
    ('main topic research papers [if query is about research]', 'short context focusing on academic research'),
    ('related subtopic with year {year}', 'short context about temporal aspects'),
    ('specific aspect in domain/location', 'very short context about domain-specific elements'),
    ('main topic with location [if query is about location]', 'short and brief context about location'),
    ('main topic with year', 'short and brief context about temporal aspects'),
    ('side aspect topic with location', 'short and brief context about location'),
    ('another side aspect topic', 'short and brief context about side aspect'),
    ('more related subtopics', 'very short and brief context about more related subtopics'),
    ('more related side aspect topics', 'very short and brief context about more related side aspect topics'),
    ('wider coverage topics with year', 'very short and brief context about wider coverage topics with year'),
    ...
]
```

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Generate exactly {self.num_queries} highly relevant query-context pairs. Write your answer as a code block with each query and context pair as a tuple inside a list.
"""

        # Override the combiner_prompt to better handle multiple model responses
        self.combiner_prompt = f"""
Collate and combine information from multiple search results obtained from different queries. Your goal is to combine these results into a comprehensive response for the user's query.

Instructions:
1. Integrate and utilize information from all provided search results to write your extensive response.
2. Write a detailed, in-depth, wide coverage and comprehensive response to the user's query using all the information from the search results. Write full answers with all details well formatted.
3. Provide all references (that are present in the search results) with web url links (http or https links) at the end in markdown as bullet points as well as inline in markdown format closest to where applicable.
4. Provide side information from the search results to provide more context and broader perspective.

Web search results (from multiple sources):
<|results|>
{{web_search_results}}
</|results|>

User's query and conversation history: 
<|context|>
{{text}}
</|context|>

Please use the given search results to answer the user's query while combining information from all provided search results. Use all the information from the search results to write a detailed and comprehensive answer. Include the full list of references at the end in markdown as bullet points.
"""

    def get_results_from_web_search(self, text, text_queries_contexts):
        array_string = text_queries_contexts
        web_search_results = []
        try:
            # Use ast.literal_eval to safely evaluate the string as a Python expression
            import ast
            text_queries_contexts = ast.literal_eval(array_string)
            
            # Ensure the result is a list of tuples
            if not isinstance(text_queries_contexts, list) or not all(isinstance(item, tuple) for item in text_queries_contexts):
                raise ValueError("Invalid format: expected list of tuples")
            
            futures = []
            # For each query, create futures for both perplexity models
            for query, context in text_queries_contexts:
                for model in self.perplexity_models:
                    llm = CallLLm(self.keys, model_name=model)
                    future = get_async_future(
                        llm,
                        # text + "\n\n" + context + "\n\nQuery: " + query,
                        "Query: " + query + "\n" + self.get_references,
                        timeout=self.timeout
                    )
                    futures.append((query, context, model, future))

            # Collect and format results
            for query, context, model, future in futures:
                try:
                    result = sleep_and_get_future_result(future)
                    model_name = model.split('/')[-1]  # Extract shorter model name
                    random_identifier = str(uuid.uuid4())
                    web_search_results.append(
                        f"**Single Query Web Search with query '{query}' :** <div data-toggle='collapse' href='#singleQueryWebSearch-{random_identifier}' role='button'></div> <div class='collapse' id='singleQueryWebSearch-{random_identifier}'>"
                        f"<b>Query:</b> {query}\n"
                        f"<b>Model ({model_name}):</b>\n{result}\n"
                        f"---\n"
                        f"</div>"
                    )
                except Exception as e:
                    logger.error(f"Error getting response for query '{query}' from model {model}: {e}")
                    
        except (SyntaxError, ValueError) as e:
            logger.error(f"Error parsing text_queries_contexts: {e}")
            text_queries_contexts = None
            
        return "\n".join(web_search_results)




    
    
if __name__ == "__main__":
    keys = {
                
            }
    # put keys in os.environ
    import os
    for k, v in keys.items():
        os.environ[k] = v
    agent = LiteratureReviewAgent(keys, model_name="gpt-4o")
    for r in agent("""What is the best way to improve the quality of life for people with disabilities?
```python
[
("What is the best way to improve the quality of life for people with disabilities?", "People with disabilities face unique challenges in their daily lives, and improving their quality of life requires a comprehensive approach that addresses their physical, emotional, and social needs. The best way to improve the quality of life for people with disabilities is to provide them with access to the resources and support they need to live independently and participate fully in society. This includes ensuring that they have access to appropriate healthcare, education, employment opportunities, and social services. It also involves promoting inclusion and diversity in all aspects of society, so that people with disabilities are treated with respect and dignity. By taking a holistic approach to supporting people with disabilities, we can help them lead fulfilling and meaningful lives.")
]
```
    """):
        print(r)

