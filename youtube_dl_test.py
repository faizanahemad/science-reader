from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
ytt_api = YouTubeTranscriptApi(
    proxy_config=GenericProxyConfig(
        https_url="https://brd-customer-hl_f6ac9ba2-zone-residential:lxbjk52v4uj8@brd.superproxy.io:33335",
    )
)
link = "https://www.youtube.com/watch?v=pxrxKPg4mZs"
fetched_transcript = ytt_api.fetch(link).to_raw_data()
# Convert transcript data to SRT format
result = []
for i, entry in enumerate(fetched_transcript, 1):
    # Calculate end time by adding duration to start time
    start_time = entry['start']
    end_time = start_time + entry['duration']
    
    # Convert times to SRT format (HH:MM:SS,mmm)
    start_str = f"{int(start_time//3600):02d}:{int((start_time%3600)//60):02d}:{int(start_time%60):02d},{int((start_time*1000)%1000):03d}"
    end_str = f"{int(end_time//3600):02d}:{int((end_time%3600)//60):02d}:{int(end_time%60):02d},{int((end_time*1000)%1000):03d}"
    
    # Format subtitle entry
    result.append(str(i))  # Subtitle number
    result.append(f"{start_str} --> {end_str}")  # Timestamp
    result.append(entry['text'])  # Text
    result.append("")  # Blank line between entries
result = "\n".join([d["text"] for d in result])
print(result)