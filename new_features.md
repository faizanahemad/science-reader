# Up next
- Links to visit [Done]
- Use Google scholar
- Store doc results from PDFs and Links we read in the conversation DB [Done].
- Speed up web based answering.
- Salient points may not be useful, best to reserve space for previous messages [Done].
- How many messages to look back -> decision
- Rerank extracted content "Slightly better results using an "agent 0" to rank results from the db query while considering the original user question, and pick only the top n."
- JSON keys [Done]
- When detailed answers is selected then scan the full document if Link is given, maybe use gpt-3.5 16K.

# High Priority
    - Test only GPT-3.5
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
    -  References and citations use in chat
    -  Use of diagrams in QnA
    -  Write sections like intro/conclusion/abstract/lit review
    -  User can provide pdf/page links in QnA, review, or chat to compare with current doc.
    -  Folder Tree structure and Tags/Collections
    - Make web search and multiple doc reading and detailed answers parallel to main call by making them api calls to same flask server.
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
    - Request model to provide code in numpy/python/pytorch instead of formulas based on its understanding.
    - Chat: Control how many times we should run web search.
    - Handle too long input exception.
    - Wikipedia and Wolfram and other structured KG integration
    - Multiple workers by making server stateless and using redis or other db for state.
    - Change the title once first message is created.
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