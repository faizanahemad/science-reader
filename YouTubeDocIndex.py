from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import json
import os
import re
import shutil
import traceback  


from ffmpeg import input as ffmpeg_input

from tqdm import tqdm
from yt_dlp import YoutubeDL  
from PIL import Image  
import imagehash  

from common import CHEAP_LLM, OPENROUTER_LLM, CacheResults, get_async_future, sleep_and_get_future_result
from call_llm import CallLLm, CallMultipleLLM
from loggers import getLoggers
import logging
from skimage import measure  
import logging  
from scipy.stats import entropy  


from loggers import getLoggers
logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(__name__, logging.INFO, logging.INFO, logging.ERROR, logging.INFO)
try:
    import cv2  
    import numpy as np  
except Exception as e:
    logger.error(f"Error importing cv2 or numpy: {e}")
    logger.error(traceback.format_exc())
  
MAX_WORKERS = 8

from hashlib import md5
from urllib.parse import urlparse


import nltk  
import pandas as pd  
import math  
  
# Download NLTK data files (if not already downloaded)  
nltk.download('punkt')  
  
def chunk_transcript(transcript, max_words=2000):  
    # Split the transcript into sentences  
    sentences = nltk.tokenize.sent_tokenize(transcript)  
    chunks = []  
    current_chunk = ''  
    word_count = 0  
    chunk_id = 1
    last_sentence = ''  # Store the last sentence of previous chunk
    
    # First pass: create basic chunks
    temp_chunks = []
    current_sentences = []
    
    for sentence in sentences:
        sentence_word_count = len(sentence.split())
        if word_count + sentence_word_count <= max_words:
            current_sentences.append(sentence)
            word_count += sentence_word_count
        else:
            if current_sentences:
                temp_chunks.append(current_sentences)
            current_sentences = [sentence]
            word_count = sentence_word_count
    
    if current_sentences:
        temp_chunks.append(current_sentences)
    
    # Second pass: create overlapping chunks
    for i, chunk_sentences in enumerate(temp_chunks):
        chunk_text = ''
        
        # Add last sentence from previous chunk if it exists
        if i > 0:
            chunk_text += temp_chunks[i-1][-1] + ' '
            
        # Add current chunk sentences
        chunk_text += ' '.join(chunk_sentences)
        
        # Add first sentence from next chunk if it exists
        if i < len(temp_chunks) - 1:
            chunk_text += ' ' + temp_chunks[i+1][0]
            
        chunks.append({
            'chunk_id': f'Chunk {chunk_id}',
            'text': chunk_text.strip()
        })
        chunk_id += 1
    
    # Convert to DataFrame  
    df_chunks = pd.DataFrame(chunks)  
    return df_chunks

def get_url_hash(url):
    """Generate a hash from URL."""
    # Remove any query parameters and fragments for consistent hashing
    # Remove trailing slash if present
    if url.endswith('/'):
        url = url[:-1]
    return md5(url.encode()).hexdigest()[:10]  # Using first 10 chars for readability


def download_video(url, folder, proxy=None):
    """Download video using yt_dlp with URL-based naming."""
    url_hash = get_url_hash(url)
    
    # Check if video was already processed
    existing_files = [f for f in os.listdir(folder) if f.startswith(f"{url_hash}_video.")]
    if existing_files:
        logger.info(f"Video already exists for URL hash: {url_hash}")
        return os.path.join(folder, existing_files[0])
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f'{folder}/{url_hash}_video.%(ext)s',
        'noplaylist': True,
    }
    if proxy:
        ydl_opts['proxy'] = proxy
    with YoutubeDL(ydl_opts) as ydl:
        logger.info(f"Downloading video with hash: {url_hash}...")
        ydl.download([url])
    
    # Return the path to the downloaded video
    for file in os.listdir(folder):
        if file.startswith(f"{url_hash}_video."):
            return os.path.join(folder, file)
    return None

def extract_audio(video_path, folder):
    """Extract audio from video using ffmpeg with consistent naming."""
    url_hash = os.path.basename(video_path).split('_')[0]  # Extract hash from video filename
    audio_path = os.path.join(folder, f'{url_hash}_audio.mp3')
    
    # Check if audio was already extracted
    if os.path.exists(audio_path):
        logger.info(f"Audio already exists for hash: {url_hash}")
        return audio_path
    
    logger.info(f"Extracting audio for hash: {url_hash}...")
    (
        ffmpeg_input(video_path)
        .output(audio_path, format='mp3', acodec='libmp3lame', ar='44100')
        .overwrite_output()
        .run(quiet=True)
    )
    return audio_path

def get_sentences_with_timing(words_with_timing):
    """
    Convert array of word timings into array of sentence timings.
    
    Args:
        words_with_timing: List of tuples (word, start_time, end_time)
        
    Returns:
        List of dicts containing sentence text and timing information
        [{'text': str, 'start': int, 'end': int}, ...]
    """
    # Common sentence-ending punctuation
    SENTENCE_ENDINGS = {
        '.', '!', '?',           # Basic endings
        '...', '।',              # Ellipsis and Devanagari danda
        '。', '！', '？',         # Chinese/Japanese endings
        '؟',                     # Arabic question mark
        '៕', '។',               # Khmer endings
        '۔',                     # Urdu full stop
    }
    
    # Additional breaking punctuation when followed by space/quotes
    BREAKING_MARKERS = {
        ';', ':', '"', '"', '"',  # Semicolon, colon, quotes
        '\n', '\r',              # Line breaks
    }
    
    current_sentence = []
    sentences_with_timing = []
    sentence_start = None
    
    for i, (word, start, end) in enumerate(words_with_timing):
        current_sentence.append(word)
        
        # Track start time of first word in sentence
        if sentence_start is None:
            sentence_start = start
        
        is_sentence_end = False
        
        # Check for sentence endings
        if any(word.endswith(ending) for ending in SENTENCE_ENDINGS):
            is_sentence_end = True
            
        # Check for breaking markers if not the last word
        elif any(word.endswith(marker) for marker in BREAKING_MARKERS):
            # Only break if followed by space/capitalized word
            if i < len(words_with_timing) - 1:
                next_word = words_with_timing[i + 1][0]
                if next_word[0].isupper():
                    is_sentence_end = True
        
        # Handle abbreviations (e.g., "Mr.", "Dr.", "U.S.A.")
        # Add more common abbreviations as needed
        COMMON_ABBREVIATIONS = {
            "mr.", "mrs.", "ms.", "dr.", "prof.",
            "sr.", "jr.", "u.s.a.", "u.k.", "u.n.",
            "a.m.", "p.m.", "etc.", "i.e.", "e.g."
        }
        if word.lower() in COMMON_ABBREVIATIONS:
            is_sentence_end = False
            
        if is_sentence_end:
            sentences_with_timing.append({
                'text': ' '.join(current_sentence),
                'start': sentence_start,
                'end': end
            })
            current_sentence = []
            sentence_start = None
    
    # Handle any remaining words as final sentence
    if current_sentence:
        sentences_with_timing.append({
            'text': ' '.join(current_sentence),
            'start': sentence_start,
            'end': words_with_timing[-1][2]
        })
    
    return sentences_with_timing


def get_transcript(audio_path, api_key):
    """Get transcript from AssemblyAI using their Python SDK.
    
    Args:
        audio_path (str): Path to audio file or URL
        api_key (str): AssemblyAI API key
    
    Returns:
        str: Transcribed text or empty string if failed
    """
    
    url_hash = os.path.basename(audio_path).split('_')[0]  # Extract hash from audio filename
    transcript_path = os.path.join(os.path.dirname(audio_path), f'{url_hash}_transcript.txt')
    sentences_with_timing_path = os.path.join(os.path.dirname(audio_path), f'{url_hash}_sentences_with_timing.json')
    
    # Check if transcript already exists
    if os.path.exists(transcript_path) and os.path.getsize(transcript_path) > 0 and os.path.exists(sentences_with_timing_path) and os.path.getsize(sentences_with_timing_path) > 0:
        logger.info(f"Transcript already exists for hash: {url_hash}")
        
        with open(sentences_with_timing_path, 'r', encoding='utf-8') as f:
            sentences_with_timing = json.load(f)
        
        with open(transcript_path, 'r', encoding='utf-8') as f:
            return f.read(), sentences_with_timing
        
    import assemblyai as aai
    from urllib.parse import urlparse

    # Configure API key
    aai.settings.api_key = api_key
    assert api_key is not None, "API key is not set"
    os.environ["ASSEMBLYAI_API_KEY"] = api_key

    try:
        logger.info("Initializing transcription...")
        transcriber = aai.Transcriber()
        
        # Start transcription
        logger.info("Starting transcription process...")
        transcript = transcriber.transcribe(
            audio_path,
        )

        # Check status and return result
        if transcript.status == aai.TranscriptStatus.error:
            logger.error(f"Transcription failed with error: {transcript.error}")
            return None, None
        
        try:
            # Get words with their start and end times
            words_with_timing = [(w.text, w.start, w.end) for w in transcript.words]
            
            # Convert to sentences with timing
            sentences_with_timing = get_sentences_with_timing(words_with_timing)
            
            # Store timing information in transcript metadata
            transcript.sentences_with_timing = sentences_with_timing
            
            logger.info(f"Transcription completed successfully with {len(sentences_with_timing)} sentences.")
            

        except Exception as e:
            logger.error(f"An error occurred during transcription: {str(e)}")
            return None, None
        
        # Save transcript
        transcript_path = os.path.join(os.path.dirname(audio_path), f'{url_hash}_transcript.txt')
        with open(transcript_path, 'w', encoding='utf-8') as f:  
            f.write(transcript.text)  
            
        # save sentences_with_timing
        with open(os.path.join(os.path.dirname(audio_path), f'{url_hash}_sentences_with_timing.json'), 'w', encoding='utf-8') as f:
            json.dump(transcript.sentences_with_timing, f, indent=4)

        return transcript.text, transcript.sentences_with_timing
    except Exception as e:
        logger.error(f"An error occurred during transcription: {str(e)}")
        return None, None

def extract_frames(video_path, folder, fps=2):  
    """Extract frames from video at specified FPS."""  
    import json  # Add import at top of file if not present
    
    frames_folder = os.path.join(folder, 'frames')  
    frames_info_path = os.path.join(folder, 'frames_info.json')
    
    if os.path.exists(frames_folder):
        logger.info(f"Frames already exist")
        return frames_folder
        
    os.makedirs(frames_folder, exist_ok=True)  
    logger.info("Extracting frames from video...")  
    
    vidcap = cv2.VideoCapture(video_path)  
    total_frames = int(vidcap.get(cv2.CAP_PROP_FRAME_COUNT))  
    video_fps = vidcap.get(cv2.CAP_PROP_FPS)  
    frame_interval = int(video_fps / fps)  
    
    frames_info = {
        "total_frames_in_video": total_frames,
        "frames": {}
    }
    
    success, image = vidcap.read()  
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        count = 0  
        saved_count = 0  
        while success:  
            if count % frame_interval == 0:  
                frame_name = f"frame{count}.jpg"
                frame_path = os.path.join(frames_folder, frame_name)  
                futures.append(executor.submit(cv2.imwrite, frame_path, image))
                
                # Calculate percentage position in video
                percentage = (count / total_frames) * 100
                frames_info["frames"][frame_name] = {
                    "frame_number": count,
                    "percentage": round(percentage, 1),
                    "time": round(count / video_fps, 2),
                    "filename": frame_name,
                    "full_path": frame_path
                }
                
                saved_count += 1  
            success, image = vidcap.read()  
            count += 1  
        for future in as_completed(futures):
            _ = future.result()
    
    vidcap.release()  
    
    # Save frames info to JSON
    with open(frames_info_path, 'w') as f:
        json.dump(frames_info, f, indent=4)
    
    logger.info(f"Extracted {saved_count} frames. Wrote frames info to {frames_info_path}")  
    return frames_folder    
  
def is_blurry(image, threshold=50):  
    """Check if an image is blurry."""  
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)  
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)  
    variance = laplacian.var()  
    return variance < threshold  
  
def is_duplicate(image1, image2, cutoff=10):
    """Check if two images are approximately duplicates.
    
    Args:
        image1: Either a file path (str) or numpy array
        image2: Either a file path (str) or numpy array
    """
    def get_hash(img):
        if isinstance(img, str):
            # If input is a file path
            return imagehash.phash(Image.open(img))
        else:
            # If input is a numpy array
            return imagehash.phash(Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    
    hash1 = get_hash(image1)
    hash2 = get_hash(image2)
    diff = hash1 - hash2
    return diff < cutoff


def has_low_entropy(image, threshold=3.0):  
    """Check if an image has low entropy."""  
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)  
    hist = cv2.calcHist([gray], [0], None, [256], [0, 256])  
    hist_norm = hist.ravel()/hist.sum()  
    ent = entropy(hist_norm, base=2)  
    return ent < threshold  
  

  
def is_scene_change(prev_image, curr_image, threshold=15):  
    """Detect scene change between two images."""  
    diff = cv2.absdiff(prev_image, curr_image)  
    non_zero_count = np.count_nonzero(diff)  
    percent_diff = (non_zero_count * 100) / diff.size  
    return percent_diff > threshold  

def filter_frame(args):
    """Filter a single frame based on defined rules."""
    frame_info, prev_image = args
    frame_path, image = frame_info
    reasons = []

    # Blur detection
    if is_blurry(image):
        reasons.append("blurry")

    # Entropy check
    if has_low_entropy(image):
        reasons.append("low_entropy")

    # Scene change and duplicate detection if previous image exists
    if prev_image is not None:
        if is_duplicate(prev_image, image):
            reasons.append("duplicate")
        if not is_scene_change(prev_image, image):
            reasons.append("no_scene_change")

    if reasons:
        return None, image, reasons
    return frame_path, image, []

def filter_frames(frames_folder):
    """Filter frames based on defined rules in parallel."""
    logger.info("Filtering frames...")
    filtered_folder = os.path.join(frames_folder, 'filtered')
    if os.path.exists(filtered_folder):
        logger.info(f"Filtered frames already exist")
        return filtered_folder
    os.makedirs(filtered_folder, exist_ok=True)

    frame_files = sorted([f for f in os.listdir(frames_folder) if f.endswith('.jpg')])
    frames_info = []
    rejection_stats = {
        "blurry": 0,
        "low_entropy": 0,
        "duplicate": 0,
        "no_scene_change": 0
    }

    for frame_file in frame_files:
        frame_path = os.path.join(frames_folder, frame_file)
        image = cv2.imread(frame_path)
        frames_info.append((frame_path, image))

    filtered_frames = []
    prev_image = None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for frame_info in frames_info:
            args = (frame_info, prev_image)
            future = executor.submit(filter_frame, args)
            futures.append(future)
            prev_image = frame_info[1]

        kept_frames = 0
        for future in tqdm(as_completed(futures), total=len(futures), desc="Filtering frames"):
            result, image, reasons = future.result()
            if result is not None:
                dest_path = os.path.join(filtered_folder, os.path.basename(result))
                cv2.imwrite(dest_path, image)
                kept_frames += 1
            else:
                # Update rejection stats
                for reason in reasons:
                    rejection_stats[reason] += 1

    # Log rejection statistics
    logger.info(f"Filtering results:")
    logger.info(f"Total frames processed: {len(frames_info)}")
    logger.info(f"Frames kept: {kept_frames}")
    logger.info("Rejection reasons:")
    for reason, count in rejection_stats.items():
        logger.info(f"- {reason}: {count} frames")

    return filtered_folder

def create_video_summary(transcript, api_keys):
    """Create a comprehensive summary of the video using GPT-4."""
    logger.info("Generating video summary...")
    
    prompt = """Please provide a comprehensive and detailed summary of this video transcript. Include:
1. Main topics and key points discussed
2. Important insights and takeaways
3. Any significant examples or case studies mentioned
4. Timeline of major discussion points
5. Key conclusions or recommendations
6. Any other information that you think is important
7. The title of the video
8. Important names, places, and organizations mentioned, any other named entities within the transcript inside <named_entities> inside <summary>
9. Important dates, times, numbers, terms and other acronyms within the transcript inside <dates_times> inside <summary>

Transcript:
<|context|>
{text}
</|context|>

Your output should follow the following format:
<title>
{{your suggestedtitle}}
</title>
<summary>
{{your suggested comprehensive, in-depth, and detailed summary}}

<named_entities>
{{your suggested list of named entities}}
</named_entities>

<dates_times>
{{your suggested list of dates, times, numbers, terms and acronyms}}
</dates_times>

</summary>


"""
    
    try:
        llm = CallLLm(api_keys, model_name=OPENROUTER_LLM[0])
        response = llm(
            prompt.format(text=transcript), 
            images=[], 
            temperature=0.7, 
            stream=False, 
            max_tokens=None, 
            system=None
        )
        title, summary = response.split("<title>\n", 1)[1].split("</title>\n", 1)[0], response.split("<summary>\n", 1)[1].split("</summary>\n", 1)[0]
        return title, summary
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        return "Error generating summary", "Error generating summary"

  
def create_image_grid(images, output_size=(1024, 1024), cell_size=(315, 315), grid_size=(3, 3)):
    """Create a grid of images with fixed output and cell sizes.
    
    Args:
        images: List of input images
        output_size: Tuple of (width, height) for final grid image (default: 512x512)
        cell_size: Tuple of (width, height) for each cell (default: 150x150)
        grid_size: Tuple of (rows, cols) for grid layout (default: 3x3)
    """
    # Create white background
    grid = np.ones((output_size[1], output_size[0], 3), dtype=np.uint8) * 255
    
    # Calculate padding and spacing
    total_cell_width = grid_size[1] * cell_size[0]
    total_cell_height = grid_size[0] * cell_size[1]
    
    h_padding = (output_size[0] - total_cell_width) // (grid_size[1] + 1)
    v_padding = (output_size[1] - total_cell_height) // (grid_size[0] + 1)
    
    count = 0
    for i in range(grid_size[0]):
        for j in range(grid_size[1]):
            if count >= len(images):
                break
                
            # Calculate position with even spacing
            x = h_padding + j * (cell_size[0] + h_padding)
            y = v_padding + i * (cell_size[1] + v_padding)
            
            # Resize image to fit cell
            img = cv2.resize(images[count], cell_size)
            
            # Add black border
            cv2.rectangle(grid, 
                         (x-2, y-2), 
                         (x+cell_size[0]+2, y+cell_size[1]+2), 
                         (0,0,0), 
                         2)
            
            # Place image
            grid[y:y+cell_size[1], x:x+cell_size[0]] = img
            
            # Add number (adjusted position for better visibility)
            cv2.putText(grid, 
                       str(count+1), 
                       (x+5, y+20), 
                       cv2.FONT_HERSHEY_SIMPLEX, 
                       0.7,  # Smaller font size
                       (0,0,255), 
                       2)
            
            count += 1
    
    return grid

def analyze_key_frames(filtered_frames_folder, video_summary, api_keys, output_folder):
    """Analyze frames using LLM and select most important ones from each group of 9."""
    logger.info("Analyzing key frames...")
    important_frames_folder = os.path.join(output_folder, 'important_frames')
    if os.path.exists(important_frames_folder):
        logger.info(f"Important frames folder already exists at {important_frames_folder}")
        return important_frames_folder
    
    # Create important_frames folder
    
    os.makedirs(important_frames_folder, exist_ok=True)
    
    
    
    frames_info_path = os.path.join(output_folder, 'frames_info.json')
    with open(frames_info_path, 'r', encoding='utf-8') as f:
        frames_info = json.load(f)
    
    # Get all frames and sort them
    frame_files = sorted([f for f in os.listdir(filtered_frames_folder) if f.endswith('.jpg')])
    
    # Split frames into groups of 9
    frame_groups = [frame_files[i:i+9] for i in range(0, len(frame_files), 9)]
    logger.info(f"Processing {len(frame_groups)} groups of frames")
    
    futures = []
    
    for group_idx, frame_group in enumerate(frame_groups):
        # Load images for this group
        images = []
        for frame in frame_group:
            img_path = os.path.join(filtered_frames_folder, frame)
            img = cv2.imread(img_path)
            images.append(img)
            
        # Pad with blank images if less than 9 frames
        while len(images) < 9:
            blank_img = np.ones((315, 315, 3), dtype=np.uint8) * 255
            images.append(blank_img)
        
        # Create grid for this group
        grid_image = create_image_grid(images)
        os.makedirs(os.path.join(output_folder, "frame_grids"), exist_ok=True)
        grid_path = os.path.join(output_folder, "frame_grids", f'frame_grid_group_{group_idx}.jpg')
        cv2.imwrite(grid_path, grid_image)
        
        prompt = """Analyze these 9 frames from a video and provide a structured response regarding importance of each frame for understanding the video.
Given the video summary below, please:
1. Rank the frames in order of importance (1 being most important)
2. For the most important frame, provide:
   - A detailed description suitable for visually impaired individuals
   - What key information it conveys about the video
   - Why it's the most significant frame
   - OCR or text in frame for context to help with accessibility
3. Briefly explain the ranking rationale for other frames
4. We value frames that are relevant to the video summary and convey important information in any form, including charts, graphs, and other visual elements.
5. We want frames that are clear and readable.

Video Summary:
{summary}

Please format your response as follows:
<ranking>
1. Frame X: [Brief explanation]
2. Frame Y: [Brief explanation]
...
</ranking>

<most_important_frame>
Frame number: X
Detailed description: [Accessibility-focused description]
Key information: [What this frame tells us about the video]
Significance: [Why this is the most important frame in this group]
OCR or text in frame: [OCR or text in frame for context to help with accessibility]
<is_this_frame_relevant>
{{yes or no, if this frame is relevant to the overall video summary and understanding of the video}}
</is_this_frame_relevant>
</most_important_frame>
"""
        
        # Create future for this group
        llm = CallLLm(api_keys, model_name=OPENROUTER_LLM[0])
        future = get_async_future(
            llm,
            prompt.format(summary=video_summary),
            images=[grid_path],
            temperature=0.7,
            stream=False,
            max_tokens=None,
            system=None
        )
        futures.append((future, frame_group, group_idx))
    
    # Process all futures and collect results
    all_analyses = []
    for future, frame_group, group_idx in futures:
        try:
            response = sleep_and_get_future_result(future, timeout=1800)
            
            # Save group analysis
            analysis_path = os.path.join(output_folder, f'frame_analysis_group_{group_idx}.txt')
            with open(analysis_path, 'w', encoding='utf-8') as f:
                f.write(response)
            
            # Extract frame number and copy most important frame
            frame_num_match = re.search(r'Frame number: (\d+)', response)
            is_this_frame_relevant_match = re.search(r'<is_this_frame_relevant>(.*?)</is_this_frame_relevant>', response, re.DOTALL)
            is_this_frame_relevant = is_this_frame_relevant_match.group(1).lower().strip().startswith("yes")
            if frame_num_match and is_this_frame_relevant:
                frame_num = int(frame_num_match.group(1))
                if frame_num <= len(frame_group):  # Ensure valid frame number
                    important_frame = frame_group[frame_num - 1]
                    src_path = os.path.join(filtered_frames_folder, important_frame)
                    dst_path = os.path.join(important_frames_folder, f'group_{group_idx}_important_{important_frame}')
                    original_frame_num = re.search(r'frame(\d+)\.jpg', important_frame)
                    if original_frame_num:
                        # Use consistent naming pattern
                        dst_filename = f"frame{original_frame_num.group(1)}.jpg"
                        dst_path = os.path.join(important_frames_folder, dst_filename)
                        
                        # Extract most important frame details
                        most_important_match = re.search(r'<most_important_frame>(.*?)</most_important_frame>', 
                                                    response, re.DOTALL)
                        if most_important_match:
                            shutil.copy2(src_path, dst_path)
                            frame_details = most_important_match.group(1)
                            frame_info = frames_info['frames'][important_frame]
                            frame_details += f"\nFrame number: {frame_info['frame_number']}, time: {frame_info['time']}, filename: {frame_info['filename']}\n"
                            details_path = os.path.join(important_frames_folder, 
                                                    f"frame{original_frame_num.group(1)}_details.txt")
                            with open(details_path, 'w', encoding='utf-8') as f:
                                f.write(frame_details)
                            
                            all_analyses.append({
                                'group': group_idx,
                                'frame': important_frame,
                                'details': frame_details
                            })
                    else:
                        logger.error(f"Failed to extract original frame number from {important_frame}")
                        
                    
            
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Error processing group {group_idx}: {str(e)}")
    
    # Save combined analysis
    combined_analysis_path = os.path.join(output_folder, 'combined_frame_analysis.txt')
    with open(combined_analysis_path, 'w', encoding='utf-8') as f:
        for analysis in all_analyses:
            f.write(f"\nGroup {analysis['group']} - {analysis['frame']}:\n")
            f.write(analysis['details'])
            f.write("\n" + "="*50 + "\n")
    
    return important_frames_folder


def process_frame_group(args):
    """Process a single group of frames and return analysis results."""
    filtered_frames_folder, frame_group, group_idx, video_summary, output_folder, api_keys, frames_info, important_frames_folder = args
   
    try:
        # Load images for this group
        images = []
        for frame in frame_group:
            img_path = os.path.join(filtered_frames_folder, frame)
            img = cv2.imread(img_path)
            images.append(img)
            
        # Pad with blank images if less than 9 frames
        while len(images) < 9:
            blank_img = np.ones((315, 315, 3), dtype=np.uint8) * 255
            images.append(blank_img)
        
        # Create grid for this group
        grid_image = create_image_grid(images)
        os.makedirs(os.path.join(output_folder, "frame_grids"), exist_ok=True)
        grid_path = os.path.join(output_folder, "frame_grids", f'frame_grid_group_{group_idx}.jpg')
        cv2.imwrite(grid_path, grid_image)
        
        prompt = """Analyze these 9 frames from a video and provide a structured response regarding importance of each frame for understanding the video.
Given the video summary below, please:
1. Rank the frames in order of importance (1 being most important)
2. For the most important frame, provide:
   - A detailed description suitable for visually impaired individuals
   - What key information it conveys about the video
   - Why it's the most significant frame
   - OCR or text in frame for context to help with accessibility
3. Briefly explain the ranking rationale for other frames
4. We value frames that are relevant to the video summary and convey important information in any form, including charts, graphs, and other visual elements.
5. We want frames that are clear and readable.

Video Summary:
{summary}

Please format your response as follows:
<ranking>
1. Frame X: [Brief explanation]
2. Frame Y: [Brief explanation]
...
</ranking>

<most_important_frame>
Frame number: X
Detailed description: [Accessibility-focused description along with entities and entities relationships and activities and other information in detail]
Key information: [What this frame tells us about the video]
Significance: [Why this is the most important frame in this group]
OCR or text in frame: [OCR or text in frame for context to help with accessibility]
<is_this_frame_relevant>
{{yes or no, if this frame is relevant to the overall video summary and understanding of the video}}
</is_this_frame_relevant>
</most_important_frame>
"""
        
        llm = CallLLm(api_keys, model_name=OPENROUTER_LLM[0])
        response = llm(
            prompt.format(summary=video_summary),
            images=[grid_path],
            temperature=0.7,
            stream=False,
            max_tokens=None,
            system=None
        )
        
        # Save group analysis
        analysis_path = os.path.join(output_folder, f'frame_analysis_group_{group_idx}.txt')
        with open(analysis_path, 'w', encoding='utf-8') as f:
            f.write(response)
        
        # Extract frame number and process important frame
        frame_num_match = re.search(r'Frame number: (\d+)', response)
        is_this_frame_relevant_match = re.search(r'<is_this_frame_relevant>(.*?)</is_this_frame_relevant>', response, re.DOTALL)
        is_this_frame_relevant = is_this_frame_relevant_match.group(1).lower().strip().startswith("yes")
        
        if frame_num_match and is_this_frame_relevant:
            frame_num = int(frame_num_match.group(1))
            if frame_num <= len(frame_group):
                important_frame = frame_group[frame_num - 1]
                original_frame_num = re.search(r'frame(\d+)\.jpg', important_frame)
                if original_frame_num:
                    most_important_match = re.search(r'<most_important_frame>(.*?)</most_important_frame>', response, re.DOTALL)
                    if most_important_match:
                        # Copy important frame to output folder
                        src_path = os.path.join(filtered_frames_folder, important_frame)
                        dst_filename = f"frame{original_frame_num.group(1)}.jpg"
                        dst_path = os.path.join(important_frames_folder, dst_filename)
                        shutil.copy2(src_path, dst_path)
                        frame_details = most_important_match.group(1)
                        frame_info = frames_info['frames'][important_frame]
                        frame_details += f"\nFrame number: {frame_info['frame_number']}, time: {frame_info['time']}, filename: {frame_info['filename']}\n"
                        details_path = os.path.join(important_frames_folder, f"frame{original_frame_num.group(1)}_details.txt")
                        with open(details_path, 'w', encoding='utf-8') as f:
                            f.write(frame_details)
                        
                        return {
                            'group': group_idx,
                            'frame': important_frame,
                            'details': frame_details,
                            'frame_num': original_frame_num.group(1)
                        }
        
        return None
        
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error processing group {group_idx}: {str(e)}")
        return None

def analyze_key_frames(filtered_frames_folder, video_summary, api_keys, output_folder):
    """Analyze frames using LLM and select most important ones from each group of 9."""
    logger.info("Analyzing key frames...")
    important_frames_folder = os.path.join(output_folder, 'important_frames')
    if os.path.exists(important_frames_folder):
        logger.info(f"Important frames folder already exists at {important_frames_folder}")
        return important_frames_folder
    
    os.makedirs(important_frames_folder, exist_ok=True)
    
    frames_info_path = os.path.join(output_folder, 'frames_info.json')
    with open(frames_info_path, 'r', encoding='utf-8') as f:
        frames_info = json.load(f)
    
    # Get all frames and sort them
    frame_files = sorted([f for f in os.listdir(filtered_frames_folder) if f.endswith('.jpg')])
    
    # Split frames into groups of 9
    frame_groups = [frame_files[i:i+9] for i in range(0, len(frame_files), 9)]
    logger.info(f"Processing {len(frame_groups)} groups of frames")
    
    # Process groups in parallel
    all_analyses = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        args_list = [(filtered_frames_folder, frame_group, idx, video_summary, output_folder, api_keys, frames_info, important_frames_folder) 
                    for idx, frame_group in enumerate(frame_groups)]
        
        for result in tqdm(executor.map(process_frame_group, args_list), total=len(args_list)):
            if result:
                all_analyses.append(result)
    
    # Save combined analysis
    combined_analysis_path = os.path.join(output_folder, 'combined_frame_analysis.txt')
    with open(combined_analysis_path, 'w', encoding='utf-8') as f:
        for analysis in all_analyses:
            f.write(f"\nGroup {analysis['group']} - {analysis['frame']}:\n")
            f.write(analysis['details'])
            f.write("\n" + "="*10 + "\n")
    
    return important_frames_folder

def create_markdown_with_images(  
    sentences_with_timing_path,  
    frames_info_path,  
    important_frames_folder,  
    output_markdown_path  
):  
    """  
    Create a markdown document by integrating important frames into the transcript at appropriate positions based on timing.  
  
    Args:  
        transcript_path (str): Path to the transcript text file.  
        sentences_with_timing_path (str): Path to the JSON file containing sentences and their timing information.  
        frames_info_path (str): Path to the JSON file containing frame timing information (`frames_info.json`).  
        important_frames_folder (str): Path to the folder containing important frame images.  
        output_markdown_path (str): Path where the output markdown file will be saved.  
  
    Returns:  
        None: The function writes the markdown content to `output_markdown_path`.  
  
    Logic:  
        1. Load the transcript, sentences with timings, and frames info.  
        2. Collect important frames and their associated timings.  
        3. Match each important frame to the corresponding sentence(s) based on timing.  
        4. Insert image markdown links into the transcript at the correct positions.  
        5. Handle corner cases where timings do not align perfectly.  
        6. Write the combined content to the output markdown file.  
    """  
    import os  
    import json  
    import re  
  
    if os.path.exists(output_markdown_path):
        logger.info(f"Markdown file already exists at {output_markdown_path}")
        return output_markdown_path
  
    # Load sentences with timings  
    with open(sentences_with_timing_path, 'r', encoding='utf-8') as f:  
        sentences_with_timing = json.load(f)  
  
    # Load frames info  
    with open(frames_info_path, 'r', encoding='utf-8') as f:  
        frames_info = json.load(f)  
  
    # Collect important frames and their timings  
    important_frames = []  
    for frame_file in os.listdir(important_frames_folder):  
        if frame_file.endswith('.jpg') or frame_file.endswith('.png'):  
            frame_path = os.path.join(important_frames_folder, frame_file)  
            frame_info = frames_info['frames'].get(frame_file)  
            if not frame_info:  
                # Try to match by frame number in filename  
                frame_number_match = re.search(r'frame(\d+)\.jpg', frame_file)  
                if frame_number_match:  
                    frame_number = int(frame_number_match.group(1))  
                    # Search for frame with matching frame_number  
                    for fname, finfo in frames_info['frames'].items():  
                        if finfo['frame_number'] == frame_number:  
                            frame_info = finfo  
                            frame_info['filename'] = fname  
                            break  
                if not frame_info:  
                    print(f"Warning: Frame info not found for {frame_file}")  
                    continue  
            else:  
                frame_info['filename'] = frame_file  
  
            important_frames.append({  
                'filename': frame_info['filename'],  
                'time': frame_info['time'],  # Time in seconds  
                'path': frame_path  
            })  
  
    # Sort important frames by time  
    important_frames.sort(key=lambda x: x['time'])  
  
    # Ensure sentences are sorted by start time  
    sentences_with_timing.sort(key=lambda x: x['start'])  
  
    # Build a list of tuples (sentence, [list of images])  
    combined_content = []  
    current_frame_idx = 0  
    total_frames = len(important_frames)  
  
    for sentence in sentences_with_timing:  
        sentence_start = sentence['start'] / 1000.0  # Convert milliseconds to seconds  
        sentence_end = sentence['end'] / 1000.0      # Convert milliseconds to seconds  
        sentence_text = sentence['text']  
  
        images_for_sentence = []  
  
        # Collect all frames that occur before the end of this sentence  
        while (current_frame_idx < total_frames and  
               important_frames[current_frame_idx]['time'] <= sentence_end):  
            frame = important_frames[current_frame_idx]  
            # Check if frame time is after the start of the sentence  
            if frame['time'] >= sentence_start - 1:  
                images_for_sentence.append(frame)  
            current_frame_idx += 1  
  
        combined_content.append({  
            'sentence': sentence_text,  
            'images': images_for_sentence  
        })  
  
    # Handle any remaining frames that did not match any sentence  
    while current_frame_idx < total_frames and False:  
        frame = important_frames[current_frame_idx]  
        # Attach to the last sentence  
        combined_content[-1]['images'].append(frame)  
        current_frame_idx += 1  
  
    # Generate markdown content  
    markdown_lines = []  
  
    for content in combined_content:  
        # Insert images before the sentence  
        for image in content['images']:  
            # Use relative path or copy images to a specific output directory if needed  
            image_relative_path = os.path.relpath(image['path'], os.path.dirname(output_markdown_path))  
            # Retrieve frame details if available  
            frame_number_match = re.search(r'frame(\d+)\.jpg', image['filename'])  
            if frame_number_match:  
                frame_number = frame_number_match.group(1)  
                details_file = os.path.join(  
                    important_frames_folder,  
                    f"frame{frame_number}_details.txt"  
                )  
                if os.path.exists(details_file):  
                    with open(details_file, 'r', encoding='utf-8') as df:  
                        frame_details = df.read()  
                    # Include frame details as a blockquote or caption  
                    markdown_lines.append(f"![Frame {frame_number}]({image_relative_path})\n")  
                    markdown_lines.append(f"*Frame {frame_number} Details:*\n")  
                    markdown_lines.append(f"> {frame_details}\n")  
                else:  
                    # Simply insert the image  
                    markdown_lines.append(f"![Frame {frame_number}]({image_relative_path})\n")  
            else:  
                # If frame number is not found, just insert the image  
                markdown_lines.append(f"![]({image_relative_path})\n")  
  
        # Insert the sentence  
        markdown_lines.append(content['sentence'] + "\n")  
  
    # Write to the output markdown file  
    with open(output_markdown_path, 'w', encoding='utf-8') as f:  
        f.writelines([line + '\n' for line in markdown_lines])  
  
    print(f"Markdown document created at {output_markdown_path}")  
    return output_markdown_path


def generate_video_report(  
    output_markdown_path,  
    video_summary_path,  
    image_descriptions_folder,  
    output_report_path,  
    max_images=10,  
    additional_guidance="",  
    api_keys=None  
):  
    """  
    Generate a comprehensive video report by incorporating the markdown transcript, video summary, and important image descriptions.  
  
    Args:  
        output_markdown_path (str): Path to the markdown file produced by 'create_markdown_with_images' containing the full transcript with images.  
        video_summary_path (str): Path to the text file containing the video title and summary.  
        image_descriptions_folder (str): Path to the folder containing image descriptions (e.g., 'frame_details.txt' files).  
        output_report_path (str): Path where the final markdown report will be saved.  
        max_images (int): Maximum number of images to include in the report.  
        additional_guidance (str): Additional instructions or customization for the report generation.  
        api_keys (dict): API keys required for LLM calls, e.g., {'OPENROUTER_API_KEY': 'your_key'}.  
  
    Returns:  
        None: The function writes the markdown report to 'output_report_path'.  
  
    Logic:  
        1. Read the markdown transcript from 'output_markdown_path'.  
        2. Read the video summary from 'video_summary_path'.  
        3. Collect and sort image descriptions based on importance (if available).  
        4. Limit the number of images to 'max_images'.  
        5. Construct a prompt for the LLM including the markdown transcript, video summary, and image descriptions.  
        6. Provide clear instructions for image insertion to the LLM.  
        7. Include any additional guidance provided.  
        8. Call the LLM to generate the report, instructing it to reference images using placeholders.  
        9. Post-process the LLM output to replace placeholders with markdown image links.  
        10. Write the final report to the output file.  
    """  
    import os  
    import glob  
    import re  
    from base import CallLLm  
  
    # Step 1: Read the markdown transcript  
    with open(output_markdown_path, 'r', encoding='utf-8') as f:  
        markdown_transcript = f.read()  
  
    # Step 2: Read the video summary  
    with open(video_summary_path, 'r', encoding='utf-8') as f:  
        video_title_and_summary = f.read()  
  
    # Step 3: Collect image descriptions  
    description_files = glob.glob(os.path.join(image_descriptions_folder, 'frame*_details.txt'))  
    image_descriptions = []  
    for desc_file in description_files:  
        # Extract frame number from filename  
        frame_number_match = re.search(r'frame(\d+)_details\.txt', os.path.basename(desc_file))  
        if frame_number_match:  
            frame_number = frame_number_match.group(1)  
            image_path = os.path.join(image_descriptions_folder, f'frame{frame_number}.jpg')  
            # Read the description  
            with open(desc_file, 'r', encoding='utf-8') as df:  
                description = df.read().strip()  
            image_descriptions.append({  
                'frame_number': frame_number,  
                'description': description,  
                'image_path': image_path  
            })  
  
    # Step 4: Limit the number of images  
    image_descriptions = image_descriptions[:max_images]  
  
    # Prepare image placeholders and descriptions  
    image_prompt_parts = []  
    for idx, img in enumerate(image_descriptions, start=1):  
        image_prompt_parts.append(f"Image {idx}: {img['description']}")  
        img['placeholder'] = f"[Image {idx} here]"  
    image_prompt = "\n\n".join(image_prompt_parts)  
  
    # Step 5: Construct the LLM prompt  
    prompt = f"""  
You are an expert content creator and reviewer. Using the markdown transcript, video summary, and the descriptions of important images provided below, please generate a comprehensive, in-depth report about the video in markdown format. The report should include:  
  
- An engaging introduction.  
- A full and extensive summary of the video.  
- Key takeaways, findings, suggestions, and lessons.  
- A detailed compilation of all the important information and insights from the video with your own comments and analysis in a separate section in a nuanced and detailed manner.  
- Incorporate the images at appropriate points by including the placeholders (e.g., [Image 1 here]) where they best fit in the narrative.  
- Include images that convey important information in any form, including charts, graphs, plots, statistics, and other visual elements.
- **Please ensure that the image placeholders are used in the text where the images should be inserted.**  
- Define and describe any jargon or less common terms at the end of the document in a glossary section.  
- Use tables or bullet points to summarize key information where appropriate.  
- Lastly include a section with your own comments and analysis, including what you think about the information presented and your own thoughts and opinions about what the video could entail and what you think the implications of the information are. Your analysis should be nuanced and detailed.  
  
{additional_guidance}  
  
**Markdown Transcript:**  
<markdown_transcript>  
{markdown_transcript}  
</markdown_transcript>  
  
**Video Title and Summary:**  
<video_title_and_summary>  
{video_title_and_summary}  
</video_title_and_summary>  
  
**Important Image Descriptions:**  
<image_descriptions>  
{image_prompt}  
</image_descriptions>  
  
Your report should be comprehensive, in-depth, detailed, nuanced, and well-structured and formatted in markdown, using headings, subheadings, lists, and other markdown features as appropriate. Remember to include the image placeholders in the text at the most appropriate locations based on the content.  
"""  
  
    # Step 6: Call the LLM to generate the report  
    llm = CallLLm(  
        keys=api_keys,  
        model_name=CHEAP_LLM[0]  # Replace with the appropriate model name  
    )  
    try:  
        response = llm(  
            prompt.strip(),  
            images=[],  # No need to pass images since we're using descriptions  
            temperature=0.7,  
            stream=False,  
            max_tokens=None,  
            system=None  
        )  
    except Exception as e:  
        print(f"Error generating report: {str(e)}")  
        return  
  
    # Step 7: Post-process the LLM output to replace placeholders with markdown image links  
    report_lines = response.split('\n')  
    final_report_lines = []  
    for line in report_lines:  
        placeholder_match = re.search(r'\[Image (\d+) here\]', line)  
        if placeholder_match:  
            idx = int(placeholder_match.group(1)) - 1  
            if 0 <= idx < len(image_descriptions):  
                img = image_descriptions[idx]  
                image_relative_path = os.path.relpath(img['image_path'], os.path.dirname(output_report_path))  
                # Replace the placeholder with markdown image syntax  
                image_markdown = f"![Image {idx + 1}]({image_relative_path})\n"  
                final_report_lines.append(image_markdown)  
            else:  
                # Invalid image index, remove the placeholder  
                final_report_lines.append('')  
        else:  
            final_report_lines.append(line)  
  
    # Step 8: Write the final report to the output file  
    with open(output_report_path, 'w', encoding='utf-8') as f:  
        f.write('\n'.join(final_report_lines))  
  
    print(f"Report generated and saved at {output_report_path}")  
    
    
def audio_extract_transcript_summary(video_path, output_folder, assemblyai_api_key, openrouter_api_key, url_hash):
    # Step 2: Extract audio  
    audio_path = extract_audio(video_path, output_folder)  
    
    # Step 3: Get transcript  
    transcript_future = get_async_future(get_transcript, audio_path, assemblyai_api_key)
    
    # Step 4: Create video summary
    transcript, sentences_with_timing = sleep_and_get_future_result(transcript_future, timeout=1800)
    
    title, summary = create_video_summary(transcript, {'OPENROUTER_API_KEY': openrouter_api_key})
    
    # Save summary
    summary_path = os.path.join(output_folder, f'{url_hash}_summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(f"{title}\n\n{summary}")
    
    return title, summary, transcript, sentences_with_timing, summary_path, audio_path
    

def overall_frame_analysis(video_path, output_folder, fps):
    # Step 4: Extract frames (can be parallel to transcript processing)  
    frames_folder = extract_frames(video_path, output_folder, fps)
  
    # Step 5: Filter frames (depends on frame extraction)  
    filtered_frames_folder = filter_frames(frames_folder)
    
    return filtered_frames_folder, frames_folder
    

def get_video_duration(video_path):
    """
    Get the duration of a video file in milliseconds.
    
    Args:
        video_path (str): Path to the video file
        
    Returns:
        float: Duration in milliseconds
    """
    try:
        # Try using ffmpeg/ffprobe first (more accurate)
        import subprocess
        cmd = [
            'ffprobe', 
            '-v', 'error', 
            '-show_entries', 'format=duration', 
            '-of', 'default=noprint_wrappers=1:nokey=1', 
            video_path
        ]
        output = subprocess.check_output(cmd).decode('utf-8').strip()
        duration_seconds = float(output)
        return duration_seconds * 1000  # Convert to milliseconds
    except Exception as e:
        logger.warning(f"Failed to get duration using ffprobe: {str(e)}")
        
        # Fallback to OpenCV
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration_seconds = frame_count / fps if fps > 0 else 0
            cap.release()
            return duration_seconds * 1000  # Convert to milliseconds
        except Exception as e2:
            logger.error(f"Failed to get duration using OpenCV: {str(e2)}")
            return None

def create_percentage_subtitles(sentences_with_timing_path, video_path, output_path):
    """
    Convert sentences with timing to a subtitle-like format with percentage timestamps
    based on actual video duration.
    
    Args:
        sentences_with_timing_path (str): Path to the JSON file containing sentences with timing
        video_path (str): Path to the video file
        output_path (str): Path where the percentage-based subtitle file will be saved
        
    Returns:
        str: Path to the created subtitle file
    """
    logger.info("Creating percentage-based subtitles...")
    
    # Load sentences with timing
    with open(sentences_with_timing_path, 'r', encoding='utf-8') as f:
        sentences_with_timing = json.load(f)
    
    if not sentences_with_timing:
        logger.error("No sentences found in timing file")
        return None
    
    # Get actual video duration in milliseconds
    total_duration_ms = get_video_duration(video_path)
    
    if not total_duration_ms:
        logger.warning("Could not determine video duration, using last sentence end time instead")
        total_duration_ms = max(sentence['end'] for sentence in sentences_with_timing)
    
    logger.info(f"Video duration: {total_duration_ms/1000:.2f} seconds")
    
    # Create subtitle content
    subtitle_lines = []
    for i, sentence in enumerate(sentences_with_timing, 1):
        # Calculate percentages and round to integers
        start_percent = round((sentence['start'] / total_duration_ms) * 100)
        end_percent = round((sentence['end'] / total_duration_ms) * 100)
        
        # Format like a subtitle file but with percentages
        subtitle_lines.append(f"{i}")
        subtitle_lines.append(f"{start_percent}% --> {end_percent}%")
        subtitle_lines.append(f"{sentence['text']}")
        subtitle_lines.append("")  # Empty line between entries
    
    # Write to file
    subtitle_lines = "\n".join(subtitle_lines)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(subtitle_lines)
    
    
    logger.info(f"Created percentage-based subtitles at {output_path}")
    return subtitle_lines

import mmh3
from common import DefaultDictQueue
@CacheResults(cache=DefaultDictQueue(1000), key_function=lambda args, kwargs: str(mmh3.hash(str(args[0]), signed=False)),
            enabled=True)
def process_youtube_video(url, assemblyai_api_key, openrouter_api_key, only_transcript=False, output_folder='output', proxy=None):  
    """Full pipeline to process YouTube video.
    
    Args:
        url (str): YouTube video URL
        assemblyai_api_key (str): API key for AssemblyAI transcription
        openrouter_api_key (str): API key for OpenRouter GPT-4o
        output_folder (str): Output directory for processed files
    """  
    
    url_hash = get_url_hash(url)
    output_folder = os.path.join(output_folder, url_hash)
    os.makedirs(output_folder, exist_ok=True)  
    
    video_path = download_video(url, output_folder, proxy=proxy)  
  
    if not video_path:  
        logger.error("Video download failed.")  
        return 
    
    with ThreadPoolExecutor(max_workers=2) as executor: 
        if not only_transcript:
            frames_future = executor.submit(overall_frame_analysis, video_path, output_folder, fps=2)
        summary_future = executor.submit(audio_extract_transcript_summary, video_path, output_folder, assemblyai_api_key, openrouter_api_key, url_hash)
        
        # Get results from both futures
        if not only_transcript:
            filtered_frames_folder, frames_folder = frames_future.result()
        title, summary, transcript, sentences_with_timing, summary_path, audio_path = summary_future.result()
        
        sentences_with_timing_path = os.path.join(output_folder, f'{url_hash}_sentences_with_timing.json')
        percentage_subtitles_path = os.path.join(output_folder, f'{url_hash}_percentage_subtitles.srt')
        subtitles = create_percentage_subtitles(sentences_with_timing_path, video_path, percentage_subtitles_path)
        
        if only_transcript:
            # delete the video_path, audio_path
            
            
            for path in [video_path, audio_path]:
                if os.path.exists(path):
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                    else:
                        os.remove(path)
                    logger.info(f"Deleted file: {path}")
            return {
                'title': title,
                'summary': summary,
                'transcript': transcript,
                'subtitles': subtitles
            }
        
    
    # Analyze and select key frames
    important_frames_folder = analyze_key_frames(
        filtered_frames_folder,
        f"{title}\n\n{summary}",
        {'OPENROUTER_API_KEY': openrouter_api_key},
        output_folder
    )
    
    # now we have transcript, title, summary, and important frames in important_frames_folder inside output_folder.
    
    # We want to create a markdown file using these. 
    
        
    sentences_with_timing_path = os.path.join(output_folder, f'{url_hash}_sentences_with_timing.json')
    frames_info_path = os.path.join(output_folder, f'frames_info.json')
    
    output_markdown_path = os.path.join(output_folder, f'{url_hash}_video_transcript.md')
        
    # Create markdown with images
    markdown_path = create_markdown_with_images(
        sentences_with_timing_path,
        frames_info_path,
        important_frames_folder,
        output_markdown_path
        
    )
    
    
    video_summary_path = os.path.join(output_folder, f'{url_hash}_summary.txt')  
    image_descriptions_folder = os.path.join(output_folder, 'important_frames')  
    output_report_path = os.path.join(output_folder, f'{url_hash}_video_report.md')  
    
    assert os.path.exists(output_markdown_path), "Markdown file not found."
    assert os.path.exists(video_summary_path), "Video summary file not found."
    assert os.path.exists(image_descriptions_folder), "Image descriptions folder not found."
    assert markdown_path == output_markdown_path, "Markdown file path does not match."
    assert summary_path == video_summary_path, "Summary file path does not match."
    assert image_descriptions_folder == important_frames_folder, "Image descriptions folder path does not match."
    
    
    # Additional guidance for the LLM (optional)  
    additional_guidance = """  
    Please ensure the report is suitable for an academic audience and includes citations where appropriate. Emphasize any surprising findings or novel insights presented in the video. Use a formal tone and include relevant references to external sources if needed.  
    """  
    
    # Generate the video report  
    generate_video_report(  
        output_markdown_path=markdown_path,  
        video_summary_path=summary_path,  
        image_descriptions_folder=important_frames_folder,  
        output_report_path=output_report_path,  
        max_images=10,  # Adjust the number as needed  
        additional_guidance=additional_guidance,  
        api_keys={'OPENROUTER_API_KEY': openrouter_api_key}  
    )  
    
    # once we have the report, we want to delete frames_folder, filtered_frames_folder, and important_frames_folder, and the video file and audio file and the frame_grids folder
    frame_grids_folder = os.path.join(output_folder, 'frame_grids')
    for folder in [frames_folder, filtered_frames_folder, important_frames_folder, video_path, audio_path, frame_grids_folder]:
        if os.path.exists(folder):
            if os.path.isdir(folder):
                shutil.rmtree(folder)
                logger.info(f"Deleted folder: {folder}")
            else:
                os.remove(folder)
                logger.info(f"Deleted file: {folder}")
            
    # we also want to delete the frame_analysis_group_*.txt files
    frame_analysis_files = glob.glob(os.path.join(output_folder, 'frame_analysis_group_*.txt'))
    for file in frame_analysis_files:
        os.remove(file)
        logger.info(f"Deleted file: {file}")

    
  
    logger.info("Processing complete.") 
    
    # return the various paths as output in a dictionary  
    return {
        'markdown_path': markdown_path,
        'summary_path': summary_path,
        'output_report_path': output_report_path,
        'percentage_subtitles_path': percentage_subtitles_path,
        'title': title,
        'subtitles': subtitles,
        'summary': summary,
        'transcript': transcript,
        
    }
    

def answer_youtube_question(question, youtube_url, assemblyai_api_key, openrouter_api_key, output_folder, proxy=None):
    """
    Answer a question about a YouTube video.
    
    Args:
        question (str): The question to answer
        youtube_url (str): The URL of the YouTube video
        assemblyai_api_key (str): The API key for AssemblyAI
        openrouter_api_key (str): The API key for OpenRouter
        output_folder (str): The folder to save the output
    """
    
    detail_dict = process_youtube_video(youtube_url, assemblyai_api_key, openrouter_api_key, only_transcript=True, output_folder=output_folder, proxy=proxy)
    summary, transcript, subtitles = detail_dict['summary'], detail_dict['transcript'], detail_dict['subtitles']
    llm = CallLLm(model_name=OPENROUTER_LLM[0], keys={'OPENROUTER_API_KEY': openrouter_api_key}  )
    
    if question.strip() == "":
        return {
            'answer': '',
            'summary': summary,
            'transcript': transcript,
            'subtitles': subtitles
        }
    # agentic prompt - do we need transcript or subtitles?
    agentic_prompt = f"""
You are a helpful assistant that can answer questions about a YouTube video. Answer concisely and briefly.

The video summary is:
{summary}

The user question is:
{question}

Now decide if you need the transcript or the subtitles to answer the question. Usually we prefer only one of them.

Your response should be in the following format:
{{
    
    "transcript_needed": "yes" or "no",
    "subtitles_needed": "yes" or "no"
}}

Just write your response in the above format inside a json code block in triple backticks.

"""
    
    response = llm(agentic_prompt).lower().strip()
    import re
    import json
    
    # Extract code block content regardless of language specification
    code_match = re.search(r'```(?:\w*\n|\w*\s)?([\s\S]*?)```', response, re.DOTALL)
    if code_match:
        extracted_code = code_match.group(1).strip()
        try:
            extracted_json = json.loads(extracted_code)
        except json.JSONDecodeError:
            # Fallback: try to extract JSON-like structure if JSON parsing fails
            json_pattern = re.search(r'{\s*"transcript_needed"\s*:\s*"(yes|no)"\s*,\s*"subtitles_needed"\s*:\s*"(yes|no)"\s*}', extracted_code)
            if json_pattern:
                extracted_json = {
                    "transcript_needed": json_pattern.group(1),
                    "subtitles_needed": json_pattern.group(2)
                }
            else:
                raise ValueError("Could not parse JSON from the extracted code block")
    else:
        # If no code block, try to find JSON directly in the response
        json_pattern = re.search(r'{\s*"transcript_needed"\s*:\s*"(yes|no)"\s*,\s*"subtitles_needed"\s*:\s*"(yes|no)"\s*}', response)
        if json_pattern:
            extracted_json = {
                "transcript_needed": json_pattern.group(1),
                "subtitles_needed": json_pattern.group(2)
            }
        else:
            raise ValueError("No code block or JSON structure found in the response")
    transcript_needed = extracted_json['transcript_needed']
    subtitles_needed = extracted_json['subtitles_needed']
    
    transcript = transcript if transcript_needed == "yes" else ''
    subtitles = subtitles if subtitles_needed == "yes" else ''
    
    prompt = f"""
You are a helpful assistant that can answer questions about a YouTube video.

The video summary is:
{summary}

The transcript is:
{transcript}

The subtitles are:
{subtitles}

The user question is:
{question}

Now answer the question based on the video summary, and transcript.
"""

    response = llm(prompt)
    return {
        'answer': response,
        'summary': summary,
        'transcript': transcript,
        'subtitles': subtitles,
        
    }
    
    
  
# Usage example  
if __name__ == "__main__": 
    # Markdown with embedded images
    # Transcript link
    # Video summary
    # Shortened and long link.
    
    youtube_url = input("Enter YouTube URL: ")  
    assemblyai_api_key = input("Enter AssemblyAI API Key: ").strip()
    openrouter_api_key = input("Enter OpenRouter API Key: ").strip()
    process_youtube_video(youtube_url, assemblyai_api_key, openrouter_api_key, proxy=None)
