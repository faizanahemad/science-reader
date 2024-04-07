# Bugs
- Auto expand of input textbox not happening. [Done]
- Run continous rendering only within answer tag once open answer tag is received. [Done]


# Startup
- Sell to Universities with On-Premise installation and per user license.
- Our USP is to reduce hallucination and increase quality of answers.
- We also enable search with LLM based summarised answers.
- Build a code execution environment for LLM based code generation.
- Teach coding using LLM.
- Make educational videos, diagrams, explanatory articles, and other content using LLM.
- Text to explanation or educational video

- Text -> Screenplay, settings and actions and dialogues (Prompt expansion like Dall-E 3) -> to Video.
- Transcript to Video
- Video to action recognition and scene identification, object detection etc to text -> Then back to video.
- Video Continuation from an existing video. Video replace parts or pixels across time by proper tracking.
- 
# Next
- Do a stage 2 filtering for reranking before LLM answers for web search. Or use reranker in stage 1 itself and check.
- Add Command R+ to list of final models and select it as default for search since it is a good RAG model. Might save uptp 6 seconds.
- Use top 4 for search and contextual reader.
- Parallelize pdf reading and web search link reading more for speed.
- For speed up of web search results, use a RAG based extraction from each link by chunking the link text by newlines and other paragraph breaks and then using the RAG to extract the most relevant part of the link. Do this without LLM call and extract about 1K token per link and then rerank again using Reranker API.
- 
- 
- No AI words setting in prompt.
- Client side key setting deprecate.
- Review screen and backend review function deprecate.
- Add the paper reading part to the chat.
- Some of the tool and function invocations can be automated by an LLM decision agent with more focus on recall.
- Debug mobile login frequent logout issues.
- Add to conference list for other fields of study.
- Improve quality of search results by searching for more results only if we don't find good results and using a priority order of systems and queries.

- Keep conversation stateful as a start but deprecate and delete after 30 days.
- Upload doc like openai paperclip button in the message box for better UX. It should open upload window directly. [Done]
  - No support for drag and drop since its not a UI feature that most people use.
- Add doc along with asking chat message. i.e. Don't block message typing and ack that a file is being uploaded.
- Adaptive chunking size for docs based on the size of the doc. [Done]
- Better retrieval by double different sized indexes (4k vs 1k or 512 vs 128) by masking the semantic similarity function and using that everywhere.
- Planner.
  - Plan what mode is needed.
  - Plan what depth and history context is needed.
  - Plan which added documents need to be read.
  - Plan what search needs to be done with what search terms.
  - What preambles and what system messages are needed.
  - What field/expert area based prompts are needed.
  - Assume we need all tools and process them and then if the planner says to use some of them then use them else discard results.
- Reference which page and part of document contributed to the part of the answer.
- Perplexity like API as an offering for companies who want Search + LLM.
- Our USP is higher quality with better speed using multiple LLM tiers
- Test a 200 page document.
  - Increase chunk size for longer docs so that less calls are made to embedding models.
- If only one doc is present then use the main LLM for answering with only text extraction to speed up answering. [Done]
- For Doc Qna, Create question and follow up question based on the document summary and then ask them in parallel. Use this in L4. [Nope] it will write too much.
- For multi-doc do [Done]
  - L4: a criss cross two layer calling strategy. First call all docs and then call all docs again. Use this in L4.
  - L1 & L2 : use the main LLM for answering with only text extraction to speed up answering. L1 less text.
  - L3: At L3 use the DocIndex submodule to answer as well as text extract to the main LLM.
- Use scraping ant or other scraper for pdf as well and 
- move to unlimited concurrency scraper for faster results. [Done] 
- Use brightdata for arxiv link. [Nope]
- Speed up Add doc time
  - Show upload progress bar.
  - Don't index docs below 20K tokens.
    - Do RAG prep only if doc is over 20K tokens.
- Enhance right click and enhance text selection.
  - Quotation in next message.
  - Summarise link
  - Search this. or Verify this.
  - Show link summary on hover.
  - Show references and citations on hover.
- Move to chat message api based system for past messages.
- Reduce thread-count. Make multiple async calls to brightdata and zenrows from one thread and then show the results as they come in using a polling mechanism.
- Speed up load time in chat by calling upvote downvote api only after the chat is loaded. [Done]
- Read more on same search results! - persist the search results and read results and then try to read the ones that were not read yet in sorted order. [Done]
  - /more command to read more of the search results. Or More button too.
    - Should work if previous was a search, link read or doc reading or general message. But work differently for each.
      - In case of plain messages, it should just go for reply module directly.
- Remove history by past summary index since we use this mostly as a search tool.
  - Use this only if infinite length message context is asked.
- Hide Sidebar on load. [Done]
- Allow to select any past message or ignore any past message for history (custom messages in history by a checkbox). [Done]
  - Clear current checkboxes once a message is sent by user.
  - Prioritize this over message length checkbox.
  - We use selected messages by running over all messages in chat and seeing if any is selected, if yes then we use this otherwise we don't.
- Logging of stdout.
- Stateless Chat for immediate uses. [Done] 
  - Make initial chats stateless always and only make then stateful if user chooses to. This way no need to make a search tab. 
  - Make this as search tab. In this search is enabled by default and chats are stateless. [WIP]
- Change websearch timing params to common configs.
- Fix doc download [Done]
- Make doc viewable within chat. [Done]
- How do we do word doc and html link doc type for docs in chat? [Done]
- On Mobile, given a pdf link or an arxiv link open in pdfjs viewer. Extra functionality since mobile forces pdf download. [Nope]
- Read link from message text itself. [Done]
- /search_exact command to search for exact text.
- read_link better [Done]

- Deprecate doc view and reviews.
- Add sonnet, haiku and mistral medium to the list of final models. [Nope]
- Use google gemini model more.
- Upload image, do ocr, and then use the text in the image [Nope]
- For Doc Qna, use two models to create answers. [Done]
- 
- Use cheaper means of web scraping
- Scrape arxiv also using zenrows and brightdata.
- Scale by money not by programming and compute.
- 
- Allow additional context to be added to the prompt. (Permanent instructions or Session level instructions) [Done]
- Give option to call other LLM like Mistral Large and Claude Opus as well. [Done]
- Settings modal where we can set system prompt, model to use for various cases, preamble, etc.
- Prompt preambles or simpler system messages set which can be selected from a dropdown. [Done]
- Functional checkboxes to use markdown formatting, think step by step, or reply so that content can be copy-pasted, or write code,  or blackmail, etc. [Done]
- Debug if SERPAPI is used? [Done] Brightdata is used.
- Gpt main UI web search, link reading, custom web search, scholar search wtih custom depth level. [Nope]
- Keep a 15 sec timeout for web scraping zenrows calls for any page.
- Block list and whitelist domains for web search for any single chat and global.
- Targetted site search like reddit or arxiv only.
- Fix remove last turn to remove the last summary as well. [Done]

- Search across chats.
- Mobile Friendly Website
- Per page pdf reading [Nope]
- Word doc without any unstructured [Nope]
- Reliability and Exception Handling and Exception capture to separate file.
- Use larger contexts everywhere. [Done]
- Enable copy of raw message. [Done]
- Enable use of gpt-4V or Claude or gemini for vision queries or image inputs. [Nope]


- Better separation between prior messages and current message/instruction. [Done]
- Improve Document RAG by generating follow up queries based on document summary and current query and running them in parallel.
  - Retrieve more chunks if you have space.
- Read more of the link by using the 16K api twice. or just use 32K model once. [Done]

- 
# Up next
- Create edit and input images in chat. [Nope]
- Links to visit [Done]
- Use Google scholar [Done]
- Store doc results from PDFs and Links we read in the conversation DB [Done].
- Salient points may not be useful, best to reserve space for previous messages [Done].
- JSON keys [Done]
- When detailed answers is selected then scan the full document if Link is given or if Multiple Docs is specified, maybe use gpt-3.5 16K. [Done]
- Fallback to bing/SERP if google search fails. [Done]
- Check in UI if text length of input message length is too long. [Done] [1000 words]
- Used length must be after prompt length + input message length. [Done]
- Pass keys as Env variables. [Done]
- Two stage process links and other results so you can start generation faster with gpt-3.5, Requery in thread queue, web search in double queue, better answer quality. [Done]
- after add paper new paper should be selected. [Done]
- Keep a default paper for all accounts "Attention is all you need paper" [Done]
- Temporary chat like bing search (or just a don't save option or scratch pad chat or like chatgpt always open with a new chat) [Done]
- Add loader initially before full page loads [Done]
- If multiple search backend are available then use all of them and show results from all of them. [Nope]
- Show only successful reads in the chat. [Done]
- word doc and html pages as well. [Nope] Print to pdf and then upload.
- If arxiv pdf url then only get citations from semantic scholar. [Done]
- If link is PDF, or link is arxiv or openreview then invoke pdf reading, don't invoke web search with pdf search. [Done]
- Parallel Rejection sampling? [Nope]
- If main url for add doc is an arxiv url or openreview url then convert it pdf url. [Done]
- Shift + Enter for newline. [Done]
- Context pollution , enable-disable button/slider for including previous chat messages, including previous documents [Done]
- Upload pdf/word file without indexing, read the file and answer directly. [Done]
- When link for reading is given use both brightdata and zenrows. [Done]
- Delete messages from a chat randomly. [Done]
- Review tab simplify and speed-up. [Done]
- Use downloaded version of readability. [Done]
- Stop using example.com for scraping. [Done]
- Link Reading, if only one link then inject into gpt4 prompt itself. Document Reading Also. [Done]
- On UI keep the input chat box valid but prevent send and show a regret model if user tries to send while previous answer is rendering [Done]
- Make rate limit on send_message api as 3 per minute per username. [Done]
- Hide the document sidebar in conversations. Open conversation first. [Done]
- Download full chat , use API call for this. Or chat shareable link which is available as non-login based link but is obscure and rate limited. [Done]
- Stop using brightdata browser, use zenrows and other hosted scrapers.
- separate current query and past messages using xml clearly in the prompt.
- Go deeper by seeing more results for the same search term.
- Replying with previous history in chat is wrong. BUG. [Done]
- When we want to use only one doc but with history then we need to use the main LLM not just the Contextual reader. [Done]
- Search query formulation with history is bad. BUG. [Done]
- Allow fully tunable prompts with jinja templates. Allow modification of all prompts in prompts.py file. We need a separate UI for this as a tab where get prompts and set prompts are available. [Nope]
- Access Control.
- Agent based style of operation for more useful answers.
- Focus on Quality of responses rather than speed since speed game is won by perplexity.
- Proper readable link to chat. Send rendered html from browser to server which can then be saved as html file [Nope]. 
- Add Try catch in zenrows js code and return normal html if Readability throws exception. Use selenium instead of nodejs and playwright. Recreate playwright browser on every call.
- Don't auto-minimise chat text. [Done]
- Dockerise and create a container which has the full python runtime and just needs keys in commandline
- Deactivate web search checkboxes if no web search keys are provided.
- Deactivate link reading and search text box if no zenrows or brightdata key provided.
- Launch as self-hosted RAG solution. With tunable prompts.
- Scroll to bottom button.
- Keep permanent instructions for a chat stored so user needs to change it only when they want.
- Use permanent instructions for a chat in the preamble or system text.
- Suggest a role and instruction text as preamble for the LLM.

- Data given to prompts has uncanny breaks in it since the data is broken based on tokens. Break data on sentences or newlines or entire messages. Similarly chunking also needs logical breaking.
- Regenerate answer with new guidance but else remaining same.
- Log user full query from api in conversations, log the prompt sent to llm and log individual variables sent for formatting to the prompt.
- Writing Tool with infill and select and change ability.
- Surf the web and personal favorite sites and then filter and make a feed for me.
- Prompt configurability, allow prompts to be configured.


- Handle server errors and faults and don't let server hangs to hang the UI input box.
- Stop Generation support at least on UI. Stop answer rendering from the backend and also send signal to backend to stop. [Nope]
- Remove file upload from mathpix. PDFs which come in search do not get uploaded to mathpix anyway.
- Use a pool of chromiums already open.
- Enable power search features like letting user ignore a site for later or creating trusted site lists. Let users specify what kind of sites might be more likely to contain what they are looking for. Perplexity Focus mode.
- Ask user a clarification question if needed, if original question is not well specified. Clarification can be a input type list select, free-form text or numeric. Do web search before clarification but use clarification to generate better answer. [Nope]
- Fast and Slow mode for chat. In fast mode use 4 docs or 30s wait with gpt-3.5, in slow mode use gpt-4 and 45s wait and 8 docs. [Done]
- Prompt xml style like claude.
- Temperature, Top-P, Samplers like Muse/Microstat and Response length control. Only for writing tool. [Nope]
- PDF annotations and highlights. or at least notes. [Nope]
- Convert Chat rendered of javascript to a generic renderer and then use it in DocIndex QnA.
- Social threads like twitter and reddit threads and blogs or videos about the paper. Use SERP or crawl based services for these.
- GPT researcher where we can say a research idea and then break it down to multiple sequential questions and then perform survey.
- UI length check
- Mark doc as starred / bookmarked / Read later.
- Home view with all papers from the selected folder or tag.
- First load doesn't show chats in correct order.
- Don't show Cites and References tab if there are no cites and references or if the doc source is not arxiv.
- BufferMemory for chat history and summary history.
- Pay all bills on time.

- Load any model and prompt it. [Nope]
- Use code model llama-code vs actual llama text model. [Nope]
- Code scrap book. [Nope]
- 
- Collections/Folders and Tags. [Nope]
  - User, Doc, Tags, Folders
  - Sort by date added, date modified, alphabetically, arxiv date
- Increase pages read but decrease timeout. [Done]
- You are an AI expert in "XYZ task".

- lite local version without web page search [Nope]
  - What all do we need to do for Local version?
  - Can we do full doc read always?
  - Enable system prompt for local version.
  - Prompt lib which separates various prompts for llm during server init based on an env variable. Prompt also by persona -> programmer, researcher, marketer, machine learning expert, configurable. etc.
  - Disable web search and other features like key store via a environment flag, Fetch the flag using api from flask into JS.
  - Local mode with no google login. [Done]
  - Don't call semantic scholar if it is not arxiv. [Done]

- Other account See via Root dev account.
- Browser pool.
- HTML code rendering bug in streaming.

- Use a bigger LLM for search query generation.
- Write a set of sample queries which test each of chat functionalities and then run them on the server to see if they are working.
- Write a set of use cases.
- Log all LLM inputs and outputs in a file with reference to feedback entities to know which LLM input and output resulted in favorable vs unfavorable feedbacks. Log which LLM was used as well.
- Make a set of block list domains which are separate for pdf search and website search.
- Enumerate instructions in your prompts with numbered list.
- Code mode (prior code is stored using a separate call to LLM to describe its functionality and then retrieved later.)
- Integrate pdfjs viewr.html into our own page so that we can track events from it and use UI events on it.

- Intro.js for first time users
- Local model for both embedding and LLM. In local mode call wizardcoder or starcoder for code additional to normal model. 
  - https://huggingface.co/upstage/Llama-2-70b-instruct-v2
  - https://github.com/vllm-project/vllm/blob/main/vllm/entrypoints/openai/api_server.py
  - https://github.com/Dicklesworthstone/llama_embeddings_fastapi_service/tree/main
  - Negative prompts for Local LLM https://github.com/oobabooga/text-generation-webui/pull/3325#issuecomment-1666959896
  - Dont freeze UI if open AI key is not present.

- Red data support with data deletion facility.
- Add few HF tools or our own tools.
- Manage the number of papers in the list using paperpile or readcube style arrangement or just show most recent top N. [Nope]
- Serve static files from nginx
- Spin up multiple servers and shard by user id / user email for workers.
- POE .com style multiple persona bots


- Keyword memory https://github.com/theubie/complex_memory but for concepts and code snippets.
- Integrate Tools like GPT researcher https://github.com/assafelovic/gpt-researcher and GPT engineer https://github.com/AntonOsika/gpt-engineer 
- https://github.com/RayVentura/ShortGPT
- Auto-complete based notepad that does both in fill and forward generation using LLM. It can also use Doc you have, use web search results, and use previous chat messages. It needs multiple boxes, 1) overall topic, 2) Any background and side info. 3) current writing box.
  - Template it using guidance library.
  - Write Tab.


# High Priority
    - Test only GPT-3.5
    - Speed up DocQnA using chat based optimisation made for chat interface.
    - Server release with internal URL
    - Literature survey chat
      - Side view of threads
      - Web search
      - Hierarchical previous chat memory
      - Ability to refer to any user's doc
      - Ability to perform custom google search for a query. With adding filetype and other filters or not.
    -  Ability to perform custom google search for a QnA. With adding filetype and other filters or not.
    -  References and citations use in QnA
    -  References and citations use in Reviews
    -  Use of diagrams in QnA
      -  https://github.com/adrai/flowchart.js
    -  Write sections like intro/conclusion/abstract/lit review
    -  User can provide pdf/page links in QnA, review, or chat to compare with current doc.
    -  Folder Tree structure and Tags/Collections
    - References and Citations based QnA as feature
    - Better error messages if keys are not working. Check in javascript itself.
    - Better overall error handling and recovery.
    - List of user's to allow / allow list which can be used to allow only certain users to use the app.
    - Key upload as json file or a csv file.
    - Streaming status and text for all long time taking api like answering and indexing and deep reader and summarization. Show the status in UI near the spinner.
    - AWS access key and use AWS bedrock through boto3
    - In the chat assistant, make ways to write sections or make the review section to write.
    - Correct toggle sidebar, with toggle function taking input of whether to toggle or not and toggling only if needed.
    - In conversational assist, keep the pdf contexts as side context for use later in the conversation, like pdf plugins in chatgpt.
    - Evergreen instructions
    - Multi-Agent with multiple persona based research assist.
    - NQS
    - TODO: `.replace(/\n/g, '<br>')` for various parts of text.
    - Handle too long input exception.
    - Multiple workers by making server stateless and using redis or other db for state.
    - Prompt optimisation and checking output of all LLM calls
    - Query reformulation if we need multi-turn for chat based Doc QnA
    
    

# Medium Priority
    -  Support to read any web-page
    -  Enhance a review with follow-up
    -  Move to Sqllite or Document DB and only store FAISS index on disk separately
    -  Multiple user's doc for review page
    -  Multiple user's doc for chat page
    -  Multi-doc search by automatic clustering of user docs and finding similar docs to current doc
    -  Ability to look at and use diagrams from the paper.
    -  Ability to create diagrams and then display them for an answer.
    -  Bring Your own 8k model
    -  If an Openreview page / Reddit page / Twitter page for a paper is present then use that in answering and reviewing
    -  Search the paper title as one of the searches in web search capability
    -  User query breakdown and reformulation based on current paper and then doing web search? 
    -  Query with longer context and handling query context separately from the query.
    -  Show sorting order for shown documents
    - Load and show PDF while indexing happens
    - Review -> Fill up a template. (Can be done by additional instructions now as well.)
    - Add a section to deep_reader_details for "similar works and extensions"
    -  Sort the shown documents by recently added to show


# Low Priority
    - Discussion Forum and support other user generated content
    - Clickable new questions to ask, Further questions one click
    - Anthropic Claude 100K 
    - Collections and Tags
    - OpenAI plugin
    - Voice input
    - Create Newsletter from multiple given links
    - Show progress of index creation
    - Show progress in writing when it is stuck.
    - How to help in second reading
    - Help in writing, literature review, intro, conclusion, abstract like sections. User can upload their existing pdf and then we can write these.
    - Scroll to part of pdf where answer is
    - Search previous questions before answering
    - Any pdf URL
    - Word doc Upload
    - GPT-3.5 16K trail and usage.
    - Parse pdf and get references.
    - Add in memory 30 min FIFO fixed size caching over load indices from disk
    
    
    


# bugs
    - Double follow-up [P2]
    - OpenAI account or rate limit exhausted bug, especially for FAISS indexing API
    - Web search for reviews searches review guidelines instead of other relevant papers.
    - Clear review additional details input after it is used once.
    - Streaming for Fixed details not happening. [Done]
    - Streaming for QnA also not happening. [Works]
    - Select the doc that was selected before in case of page refresh [Done]
    - What happens when no conversation exists
    - After add paper new paper should be selected.

# Bills
- Digitalocean
- OpenAI
- Google search json api
- Bing search API
- Ai21
- Cohere rerank
- Mathpix
- brightdata.com scraping browser

# Research 
- Compare reviews with Neurips reviews.
- How well can multi-modal or captioning models understand scientific diagrams.

`sudo apt install chromium-browser`

[Chrome install](https://www.wikihow.com/Install-Google-Chrome-Using-Terminal-on-Linux)

[Chrome Driver](https://chromedriver.chromium.org/downloads)

`sudo apt-get install unzip`

# test cases for DB migration
  - Use 2 users from diff browsers
  - Can we do upsert? If same doc is added by two different users



- Oobabooga
- Text-generation-ui

Zenrows
50$ - 250000 - 10 - 5 // 50K // 1$ per K

Scraping ant
20$ - 100000 - Inf - 10 // 10K // 2$ per K [XX]

Scraping Bee
50$ - 150000 - 5 - 5 // 30K // 1.66$ per K


Scrape-it cloud
30$ - 50000 - 5 - 10 // 5K // 6$ per K




