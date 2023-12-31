# Up next
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
- Temperature, Top-P, Samplers like Muse/Microstat and Response length control. [Nope]
- 
- Convert Chat rendered of javascript to a generic renderer and then use it in DocIndex QnA.

- First load doesn't show chats in correct order.
- Don't show Cites and References tab if there are no cites and references or if the doc source is not arxiv.
- BufferMemory for chat history and summary history.
- Pay all bills on time.


- Collections/Folders and Tags.
  - User, Doc, Tags, Folders
  - Sort by date added, date modified, alphabetically, arxiv date
- Increase pages read but decrease timeout.
- You are an AI expert in "XYZ task".

- lite local version without web page search
  - What all do we need to do for Local version?
  - Can we do full doc read always?
  - Prompt lib which separates various prompts for llm during server init based on an env variable. Prompt also by persona -> programmer, researcher, marketer, machine learning expert, configurable. etc.
  - Disable web search and other features like key store via a environment flag, Fetch the flag using api from flask into JS.
  - Local mode with no google login.
  - Don't call semantic scholar if it is not arxiv.
- support seeing raw text from the model.
- Other account See via Root dev account.
- Browser pool.
- HTML code rendering bug in streaming.
- Retrieve more chunks if you have space.
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
- Manage the number of papers in the list using paperpile or readcube style arrangement or just show most recent top N.
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
    -  Social threads like twitter and reddit threads and blogs or videos about the paper. Use SERP or crawl based services for these.
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