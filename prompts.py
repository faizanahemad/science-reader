import os
from copy import deepcopy

class CustomPrompts:
    def __init__(self, llm, role):
        self.llm = llm
        self.role = role
        # TODO: decide on role prefixes needed or not.
        # 4. Provide code in python if asked for code or implementation.
        # Use markdown formatting to typeset and format your answer better.
        self.complex_output_instructions = """Use the below rules while providing response.
1. Use markdown lists and paragraphs for formatting.
2. Output any relevant equations in latex format putting each equation in a new line in separate '$$' environment.
3. Provide references or links within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format."""

        self.simple_output_instructions = """Use the below rules while providing response.
1. Use markdown lists and paragraphs for formatting.
2. Provide references within the answer inline itself immediately closest to the point of mention or use. Provide references in a very compact format."""
        self.gpt4_prompts = dict(
            streaming_followup=f"""Provide answer to a follow up question which is based on an earlier question. Answer the followup question or information request from context (text chunks of larger document) you are provided. 
Followup question or information request is given below.
"{{followup}}"

Few text chunks from within the document to answer this follow up question as below.
"{{fragment}}"
Keep the earlier question in consideration while answering.
Previous question or earlier question and its answer is provided below:

Earlier Question: "{{query}}"

Earlier Answer:
"{{answer}}"

Keep the earlier question in consideration while answering.
{self.complex_output_instructions}

Current Question: {{followup}}
Answer: 
""",
            short_streaming_answer_prompt=f"""Answer the question or query given below using the given context (text chunks of larger document) as a helpful reference. 
Question or Query is given below.
{{query}}

Summary of the document is given below:
{{full_summary}}
Few text chunks from the document to answer the question below:
'''{{fragment}}'''

Write informative, comprehensive and detailed answer below.
""",
            running_summary_prompt=f"""We are reading a large document in fragments sequentially to write a continuous summary.
'''{{document}}'''
{{previous_chunk_summary}}
{{summary}}
Instructions for this summarization task as below:
- Ignore references.
- Provide detailed, comprehensive, informative and in-depth response.
- Include key experiments, experimental observations, results and insights.
- Use markdown for formatting. Use lists and paragraphs.

Summary:
""",
            retrieve_prior_context_prompt="""You are given conversation details between a human and an AI. Based on the given conversation details and human's last response or query we want to search our database of responses.
You will generate a contextualised query based on the given conversation details and human's last response or query. The query should be a question or a statement that can be answered by the AI or by searching in our semantic database.
Ensure that the rephrased and contextualised version is different from the original query.
The summary of the conversation is as follows:
{requery_summary_text}

The last few messages of the conversation are as follows:
{previous_messages}

The last message of the conversation sent by the human is as follows:
{query}

Rephrase and contextualise the last message of the human as a question or a statement using the given previous conversation details so that we can search our database.
Rephrased and contextualised human's last message:
""",
            long_persist_current_turn_prompt="""You are given conversation details between a human and an AI. You will summarise the conversation provided below.
The older summary of the conversation is as follows:
'''{older_summary}'''

The recent summary of the conversation is as follows:
'''{previous_summary}'''

The last few messages of the conversation from which we will derive the summary are as follows:
'''
{previous_messages}
'''
             
Please summarize the conversation very informatively, in great detail and depth. Your summary should be detailed, comprehensive, thoughtful, insightful, informative, and in-depth. Ensure you capture all nuances and key points from the dialogue. Capture all essential details mentioned by both user and assistant.
If we are answering questions on a story, article or some other context then we should provide a summary of the story or article as well, since we will later just ask questions and use the summary to answer the questions.

Format your summary using markdown, starting with a long comprehensive overview paragraph. Follow this with in depth bullet points with good detailing highlighting about all the details of the conversation. Finally, conclude with an extensive final remark about the overall conversation including any plans or action items. Mention all solutions, suggestions, references, methods and techniques we discussed in depth and proper detail. Capture any solutions, ideas, thoughts, suggestions, action items we had discussed in depth and comprehensively.

Prioritise clarity, informativeness, wide coverage, density and depth in your summary to fully represent the conversation and all its smaller details. Keep your response dense in information and details.
Write down any special rules or instructions that the AI assistant should follow in the conversation as well.

Conversation Summary:
""",
            persist_current_turn_prompt="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
Write a new summary of the conversation. Capture the salient, important and noteworthy aspects and details from the user query and system response. Your summary should be detailed, comprehensive and in-depth.
Capture all important details in your conversation summary including code, factual details, names and other details mentioned by the human and the AI. 
Preserve important details that have been mentioned in the previous summary especially including factual details and references.
Write down any special rules or instructions that the AI assistant should follow in the conversation as well.

The previous summary and salient points of the conversation is as follows:
'''{previous_summary}'''

Previous messages of the conversation are as follows:
'''{previous_messages_text}'''

The last 2 messages of the conversation from which we will derive the summary and salient points are as follows:
User query: '''{query}'''
System response: '''{response}'''

Write a summary of the conversation using the previous summary and the last 2 messages. Please summarize the conversation very informatively, in great detail and depth.
Conversation Summary:
""",


            chat_slow_reply_prompt=f"""You are given conversation details between human and AI. We will be replying to the user's query or message given.
{{conversation_docs_answer}}{{doc_answer}}{{web_text}}{{link_result_text}}{{summary_text}}{{previous_messages}}
{{permanent_instructions}}
The most recent message of the conversation sent by the user now to which we will be replying is given below.
user's most recent message:\n'''{{query}}'''
Response to the user's query:
""",
            document_search_prompt="""You are given a question and conversation summary of previous messages between an AI assistant and human as below. 
The question which is given below needs to be answered by using a document context that will be provided later. 
For now we need to rephrase this question better using the given conversation summary.

Current Question: '''{context}'''

Previous conversation summary: '''{doc_context}'''

We want to rephrase the question to help us search our document store for more information about the query.

Generate one well specified search query as a valid python list. 
Instructions for how to generate the queries are given below.
1. Output should be only a python list of strings (a valid python syntax code which is a list of strings). 
2. Convert abbreviations to full forms and correct typos in the query using the given context.
3. Your output will look like a python list of strings like below.
["query_1"]

Output only a valid python list of web search query strings.
""",
            web_search_question_answering_prompt=f"""<task>Your role is to provide an answer to the user question incorporating the additional information you are provided within your response.</task>
Question is given below:
"{{query}}"
Relevant additional information with url links, titles and document context are mentioned below:
"{{additional_info}}"

Continue the answer ('Answer till now' if it is not empty) by incorporating additional information from other documents. 
Answer by thinking of Multiple different angles that 'the original question or request' can be answered with. Focus mainly on additional information from other documents. Provide the link and title before using their information in markdown format (like `[title](link) information from document`) for the documents you use in your answer.

{self.complex_output_instructions}
Question: '''{{query}}'''
Answer till now (partial answer, can be empty): '''{{answer}}'''
Write answer using additional information below.
""",

            get_more_details_prompt=f"""Continue writing answer to a question or instruction which is partially answered. 
Provide new details from the additional information provided if it is not mentioned in the partial answer already given. 
Don't repeat information from the partial answer already given.
Question is given below:
"{{query}}"
Answer till now (partial answer already given): '''{{answer}}'''

Relevant additional information from the same document context are mentioned below:
'''{{additional_info}}'''

Continue the answer ('Answer till now') by incorporating additional information from this relevant additional context. 
{self.complex_output_instructions}

Continue the answer using additional information from the documents.
""",
            paper_details_map = {
            "methodology": """
Read the document and provide information about "Motivation and Methodology" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What do the authors do in this overall work (i.e. their methodology) with details.
    - Detailed methodology and approach described in this work.
    - what problem do they address ?
    - how do they solve the problem, provide details?
    - Why do they solve this particular problem?
    - what is their justification in using this method? Why do they use this method? 
    - Any insights from their methods
    - Any drawbacks in their method or process
""",
            "previous_literature_and_differentiation": """
Read the document and provide information about "Previous Literature and Background work" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What is this work's unique contribution over previous works?
    - what previous literature or works are referred to?
    - How are the previous works relevant to the problem this method is solving?
    - how their work is different from previous literature?
    - What improvements does their work bring over previous methods.
""",
            "experiments_and_evaluation":"""
Read the document and provide information about "Experiments and Evaluation" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - How is the proposed method/idea evaluated?
    - What metrics are used to quantify their results?
    - what datasets do they evaluate on?
    - What experiments are performed?
    - Are there any experiments with surprising insights?
    - Any other surprising experiments or insights
    - Any drawbacks in their evaluation or experiments
""",
            "results_and_comparison": """
Read the document and provide information about "Results" of the work.
Cover the below points while answering and also add other necessary points as needed.
    - What results do they get from their experiments 
    - how does this method perform compared to other methods?
    - Make markdown tables to highlight most important results.
    - Any Insights or surprising details from their results and their tables
""",
            "limitations_and_future_work":"""
Read the document and provide information about "Limitations and Future Work" of the work. 
Cover the below points while answering and also add other necessary points as needed.
    - What are the limitations of this method, 
    - Where and when can this method or approach fail? 
    - What are some further future research opportunities for this domain as a follow up to this method?
    - What are some tangential interesting research questions or problems that a reader may want to follow upon?
    - What are some overlooked experiments which could have provided more insights into this approach or work.
""",
            }
        )

    @property
    def prompts(self):
        if self.llm == "gpt4":
            prompts = self.gpt4_prompts
        elif self.llm == "gpt3":
            prompts = self.gpt4_prompts
        elif self.llm == "llama":
            raise ValueError(f"Invalid llm {self.llm}")
        elif self.llm == "claude":
            prompts = self.gpt4_prompts
        else:
            raise ValueError(f"Invalid llm {self.llm}")
        return prompts

    @property
    def paper_details_map(self):
        prompts = self.prompts
        return prompts["paper_details_map"]

    @property
    def streaming_followup(self):
        prompts = self.prompts
        return prompts["streaming_followup"]

    @property
    def short_streaming_answer_prompt(self):
        prompts = self.prompts
        return prompts["short_streaming_answer_prompt"]

    @property
    def running_summary_prompt(self):
        prompts = self.prompts
        return prompts["running_summary_prompt"]

    @property
    def retrieve_prior_context_prompt(self):
        prompts = self.prompts
        return prompts["retrieve_prior_context_prompt"]

    @property
    def persist_current_turn_prompt(self):
        prompts = self.prompts
        return prompts["persist_current_turn_prompt"]

    @property
    def long_persist_current_turn_prompt(self):
        prompts = self.prompts
        return prompts["long_persist_current_turn_prompt"]

    @property
    def chat_fast_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_fast_reply_prompt"]

    @property
    def chat_slow_reply_prompt(self):
        prompts = self.prompts
        return prompts["chat_slow_reply_prompt"]

    @property
    def coding_prompt(self):
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")


        rules = """
## Rules for writing code (especially code that needs to be executed and run) and making diagrams, designs and plots.
- Write python code that needs to be executed only inside <code action="execute"> and </code> tags. We can only execute python code.
- Write executable code in case user asks to test already written code, but ensure that it is safe code that does not delete files or have side effects. 
- When you write code that needs execution indicate that it needs to be executed by using the <code action="execute"> and </code> tags and also mentioning a comment within code which say "# execute".
- You are allowed to read files from the input directory {input_directory} and write files to the directory {output_directory}.
- If asked to read files, only read these filenames from the input directory: {input_files}.
- You can use only the following libraries: pandas, numpy, scipy, matplotlib, seaborn, scikit-learn, networkx, pydot etc.
- Certain diagrams can be made using mermaid js library as well. First write the mermaid diagram code inside <pre class="mermaid"> and </pre> tags.
- You can also make diagrams using mermaid js library. You can make Flowcharts, Sequence Diagrams, Gantt diagram, Class diagram, User Journey Diagram, Quadrant Chart, XY Chart. Write the diagram code inside <pre class="mermaid"> and </pre> tags so that our mermaid parser can pick it and draw it.
- You are allowed to make diagrams using draw.io or diagrams.net xml format. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```).
- Use draw.io or diagrams.net to make diagrams like System design diagrams, complex scientific processes, flowcharts, network diagrams, architecture diagrams etc. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```). so that our drawio parser can pick it and draw it.
- Write code with indicative variable names and comments for better readability that demonstrate how the code is trying to solve our specific use case.
- Code in python preferably and write code in a single cell for code execution tasks.
- Write full and complete executable code since our code environment is stateless and does not store any variables or previous code/state.
- You are allowed to make plots and graphs and save them to the output directory with filename prefix as {plot_prefix} and extension as jpg.
- You are allowed to write output to stdout or to a file (in case of larger csv output) with filename prefix as {file_prefix}.
- Remember to write python code that needs to be executed only inside <code action="execute"> and </code> tags. We can only execute python code.
- Make high quality plots with clear and extensive labels and explanations.
- Allowed to read csv, excel, parquet, tsv only.
- Do not leak out any other information like OS or system info, file or directories not permitted etc. Do not run system commands or shell commands.
- Do not delete any files.
- Do not use any other libraries other than the ones mentioned above.
""" + f"\n- The current date is '{date}', year is {year}, month is {month}, day is {day}.\n"
        return rules


    @property
    def query_is_answered_by_search(self):
        """"""
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        import re

        def parse_llm_output(llm_output):
            # Initialize a dictionary to hold the parsed data
            parsed_data = {
                "thoughts": None,
                "answered_already_by_previous_search": None,
                "web_search_needed": None,
                "web_search_queries": []
            }

            # Define regex patterns for extracting information
            thoughts_pattern = r"<thoughts>(.*?)</thoughts>"
            answered_already_pattern = r"<answered_already_by_previous_search>(.*?)</answered_already_by_previous_search>"
            web_search_needed_pattern = r"<web_search_needed>(.*?)</web_search_needed>"
            web_search_queries_pattern = r"<query>(.*?)</query>"

            # Extract information using regex
            thoughts_match = re.search(thoughts_pattern, llm_output, re.DOTALL)
            answered_already_match = re.search(answered_already_pattern, llm_output, re.DOTALL)
            web_search_needed_match = re.search(web_search_needed_pattern, llm_output, re.DOTALL)
            web_search_queries_matches = re.findall(web_search_queries_pattern, llm_output, re.DOTALL)

            # Update the dictionary with the extracted information
            if thoughts_match:
                parsed_data["thoughts"] = thoughts_match.group(1).strip()
            if answered_already_match:
                parsed_data["answered_already_by_previous_search"] = answered_already_match.group(
                    1).strip().lower() == "yes"
            if web_search_needed_match:
                parsed_data["web_search_needed"] = web_search_needed_match.group(1).strip().lower() == "yes"
            if web_search_queries_matches:
                parsed_data["web_search_queries"] = [query.strip() for query in web_search_queries_matches]

            return parsed_data

        prompt = f"""You are an expert AI system which determines whether our search results are useful and can answer a user query or not. If our search results can't answer the user query then you will decide if we need to do more web search and write two new web search queries for performing search again.
The current date is '{date}', year is {year}, month is {month}, day is {day}. 

Previous web search queries are given below (empty if no web search done previously):
'''{{previous_web_search_queries}}'''

Previous web search results are given below (empty if no web search done previously):
'''{{previous_web_search_results}}'''

Previous web search results text is given below:
'''{{previous_web_search_results_text}}'''

Conversation context:
'''{{context}}'''

Current user message is given below: 
'''{{query}}'''

# Note: You can use the current date ({date}) and year ({year}) in the web search queries that you write.

Output Template is given below.
<planner>
    <thoughts>Your thoughts in short on whether the previous web search queries and previous web search results are sufficient to answer the user message written shortly.</thoughts>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search_needed>yes</web_search_needed>
    <web_search_queries>
        <query>web search query 1</query>
        <query>web search query 2 with year ({year}) or date ({date}) if needed</query>
    </web_search_queries>
</planner>

Template if the user query is already answered by previous search:
<planner>
    <thoughts>Your thoughts on whether the previous web search queries and previous web search results are sufficient to answer the user message.</thoughts>
    <answered_already_by_previous_search>yes</answered_already_by_previous_search>
    <web_search_needed>no</web_search_needed>
    <web_search_queries></web_search_queries>
</planner>

Write your output decision in the above xml format.
"""
        return prompt, parse_llm_output

    @property
    def planner_checker_prompt(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""You are an expert AI system that determines which function to call (function calling and tool usage). Your task is to decide if we need to do web queries, need to read any uploaded docs, if we need to check our answer for further web search, and what queries we need to generate to search our documents or the web.
You are given a user message and conversation context as below. If we had done web search previously then you will also be given the web search queries and results so that you can decide if we need to do more web search or not. 
If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not.
The current date is '{date}', year is {year}, month is {month}, day is {day}. 



Available Document Details are given below (empty if no documents uploaded):
'''{{document_details}}'''

Now based on given user message and conversation context decide if we need to do web search, read any uploaded documents, check our answer for further web search, and generate queries to search our documents or the web.
Generate 4 well specified and diverse web search queries if web search is needed. 

Your output should look be an xml tree with our reasons and decisions like below example format.
<planner>
    <thoughts>Based on the user message and conversation context, the user query is in science domain, we do not have previous links and the question can't be answered by LLM itself so we need to do web search, also since we have attached documents which are relevant so generate queries to search our documents.</thoughts>
    <domain>Science</domain>
    <is_question_about_finance_stocks_mutual_fund_etf>no<is_question_about_finance_stocks_mutual_fund_etf>
    <company_stock_fund_etf_name></company_stock_fund_etf_name>
    <code_execution_data_analysis_needed>no</code_execution_data_analysis_needed>
    <diagramming_asked_explicitly></diagramming_asked_explicitly>
    <is_diagram_needed_for_clear_explanation>no</is_diagram_needed_for_clear_explanation>
    <suggested_diagram_type></suggested_diagram_type>
    <use_writing_pad>no</use_writing_pad>
    <use_memory_pad>no</use_memory_pad>
    <web_search_needed_for_clear_explanation>yes</web_search_needed_for_clear_explanation>
    <web_search_asked_explicitly>yes</web_search_asked_explicitly>
    <web_search_type>general</web_search_type>
    <read_document>yes</read_document>
    <web_search_queries>
        <query>diverse google search query based on given document</query>
        <query>different_web_query based on the document and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

web_search will usually be yes if we have not done any web search previously or if the question is looking for latest information that an LLM can't answer. For programming framework help or general knowledge questions we may not need to do web search always but for frameworks or programming questions where we are not certain if you can answer by yourself then perform web search.

We have the following list of domains to choose from:
<select class="form-control" id="field-selector">
    <option>None</option>
    <option>Science</option>
    <option>Arts</option>
    <option>Health</option>
    <option>Psychology</option>
    <option>Finance</option>
    <option>Mathematics</option>
    <option>QnA</option>
    <option>AI</option>
    <option>Software</option>
</select>

Few examples are given below.
<example 1>

Current user message:
'''What are the best ways to improve my health?'''

conversation context:
'''I am having bad sleep and feel tired a lot. Doctor suggested to drink lots of water as well.'''

Previous Web Search Queries:
["how to improve health", "how does drinking more water help improve my body?", "how to improve health and sleep by drinking water and exercising", "Ways to improve cardiovascular health in {year}"]

Previous Web Search Results in mardown format:
'''
[title1](link2) information from link1
[title2](link2) information from link2
'''

Available Document Details:
'''
[Document1](#doc_1) information from doc1
[Document2](#doc_2) information from doc2
'''

Valid xml tree with our reasons and decisions:
<planner>
    <thoughts>Based on the user message and conversation context we do not need to do web search and but we need search our documents and generate queries to search our documents.</thoughts>
    <domain>Health</domain>
    <answered_already_by_previous_search>yes</answered_already_by_previous_search>
    <web_search>no</web_search>
    <read_document>yes</read_document>
    <web_search_queries>
    </web_search_queries>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What are the benefits of drinking more than 2 litre of water</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>Sleeping 8 hours good or bad</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>How to improve cardiovascular health</query></document_query>
    </document_search_queries>
</planner>
    

</example 1>

# Note: Each web search query is different and diverse and focuses on different aspects of the question and conversation context.

<example 2>

Current user message:
'''What is the price to earnings ratio of Apple Inc?'''

conversation context:
'''I am thinking of investing in Apple Inc and want to know the price to earnings ratio.'''

Previous Web Search Queries:
["Apple Inc price to earnings ratio", "Apple Inc financials", "Apple Inc stock price", "Apple Inc price to earnings ratio in {year}"]

Previous Web Search Results in mardown format:
'''
[title1](Link1) information from link1 - no information on price to earnings ratio, price found.
'''

Available Document Details:
'''
[Apple Q4 earnings](#doc_1) information from doc1 about earnings
[Apple Inc Financials](#doc_2) information from doc2 about financials
[Apple Mac Documentation](#doc_3) information from doc3 about Macbooks - not relevant.
'''

Valid xml tree with our reasons and decisions:
<planner>
    <thoughts>Based on the user message and conversation context we need to do web search and also search our documents on apple financials.</thoughts>
    <domain>Finance</domain>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search>yes</web_search>
    <read_document>yes</read_document>
    <web_search_queries>
        <query>Apple Inc stock price in {date}</query>
        <query>Apple Inc earning in {month} {year}</query>
        <query>Apple Inc financial ratios</query>
    </web_search_queries>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What are the earnings of Apple Inc in Q4</query></document_query>
        <document_query><document_id>#doc_2</document_id><query>What are the financial ratios of Apple Inc</query></document_query>
        <document_query><document_id>#doc_1</document_id><query>What are the earnings and profits of Apple Inc</query></document_query>
    </document_search_queries>
</planner> 

</example 2>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

<example 3>

Current user message:
'''What are the emerging trends in AI and large language models?'''

conversation context:
'''I am working on a new language model and want to know what are the latest trends in the field. I can also use ideas from broader developments in AI.'''

Previous Web Search Queries:
[]

Previous Web Search Results in mardown format:
''''''

Available Document Details:
''''''

Valid xml tree with our reasons and decisions:
<planner>
    <thoughts>Based on the user message and conversation context we need to do web search since we have not done any web search and the question is looking for latest information that an LLM can't answer.</thoughts>
    <domain>AI</domain>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search>yes</web_search>
    <read_document>no</read_document>
    <web_search_queries>
        <query>Emerging trends in AI in {year}</query>
        <query>Emerging trends in large language models in {year}</query>
        <query>Recent research works in AI</query>
        <query>Recent papers in large language models arxiv</query>
    </web_search_queries>
    <document_search_queries>
    </document_search_queries>
</planner>

</example 3>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

<example 4>

Current user message:
'''Write how to generate fibonacci numbers in python using recursion and iteration.'''

conversation context:
'''I am learning python and want to understand various algorithms in python.'''

Previous Web Search Queries:
[]

Previous Web Search Results in mardown format:
''''''

Available Document Details:
''''''

Valid xml tree with our reasons and decisions:

<planner>
    <thoughts>Based on the user message and conversation context we do not need to do web search since this question is easy for an LLM to answer and the question is looking for programming help.</thoughts>
    <domain>Software</domain>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search>no</web_search>
    <read_document>no</read_document>
    <web_search_queries>
    </web_search_queries>
    <document_search_queries>
    </document_search_queries>
</planner>

</example 4>

<example 5>

Current user message:
'''Methods to optimise LLM for large scale deployment.'''

conversation context:
'''I am working on a new language model and want to know how to deploy it at scale.'''

Previous Web Search Queries:
["optimise LLM for deployment", "deploying large language models"]

Previous Web Search Results in mardown format:
'''
[title1](link1) information from link1 - no information on deployment, only on training.
[Optimizing LLMs for Speed and Memory](https://huggingface.co/docs/transformers/main/en/llm_tutorial_optimization)
In this guide, we will go over the effective techniques for efficient LLM deployment:
Lower Precision: Research has shown that operating at reduced numerical precision, namely 8-bit and 4-bit can achieve computational advantages without a considerable decline in model performance.
Flash Attention: Flash Attention is a variation of the attention algorithm that not only provides a more memory-efficient approach but also realizes increased efficiency due to optimized GPU memory utilization.
Architectural Innovations: Considering that LLMs are always deployed in the same way during inference, namely autoregressive text generation with a long input context, specialized model architectures have been proposed that allow for more efficient inference. The most important advancement in model architectures hereby are Alibi, Rotary embeddings, Multi-Query Attention (MQA) and Grouped-Query-Attention (GQA).
'''

Available Document Details:
''''''

Valid xml tree with our reasons and decisions:
<planner>
    <thoughts>Previous search only has one relevant result, we would want at least five relevant results as such we should run web search again with more relevant queries. We should break the problem down based on the previous link and queries</thoughts>
    <domain>AI</domain>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <is_question_about_stocks_mutual_fund_etf>no<is_question_about_stocks_mutual_fund_etf>
    <company_stock_fund_etf_name></company_stock_fund_etf_name>
    <code_execution_data_analysis>no</code_execution_data_analysis>
    <use_writing_pad>no</use_writing_pad>
    <use_memory_pad>no</use_memory_pad>
    <web_search>yes</web_search>
    <read_document>no</read_document>
    <web_search_queries>
        <query>Deploying large language models at scale</query>
        <query>Efficient deployment of large language models</query>
        <query>Techniques for Optimising LLMs for deployment</query>
        <query>Optimising LLMs for deployment in {year}</query>
    </web_search_queries>
    <document_search_queries>
    </document_search_queries>
</planner>

</example 5>

<example 6>

Current user message:
'''Summarise how Zomato performed in the last quarter.'''

Conversation context:
'''I am thinking of investing in Zomato and want to know how they have been performing recently.'''

Previous Web Search Queries:
[]

Previous Web Search Results in mardown format:
''''''

Available Document Details:
'''
[Quarterly report for Zomato](#doc_1) information from doc1 regarding last quarter performance on zomato.
'''

Valid xml tree with our reasons and decisions:
<planner>
    <thoughts>Based on the user message and conversation context we do not need to do web search and but we need search our documents and generate queries to search our documents.</thoughts>
    <domain>Finance</domain>
    <answered_already_by_previous_search>yes</answered_already_by_previous_search>
    <web_search>no</web_search>
    <read_document>yes</read_document>
    <web_search_queries>
    </web_search_queries>
    <document_search_queries>
        <document_query><document_id>#doc_1</document_id><query>What are the financials of Zomato in the last quarter</query></document_query>
        <document_query><document_id>#doc_1</document_id><query>How did Zomato perform in the last quarter</query></document_query>
        <document_query><document_id>#doc_1</document_id><query>What are the profits of Zomato in the last quarter</query></document_query>
    </document_search_queries>
</planner>

</example 6>

Current user message: 
'''{{context}}'''

Conversation context:
'''{{doc_context}}'''

Previous Web Search Queries (empty if no previous queries):
'''{{web_search_queries}}'''

Previous Web Search Results (empty if no previous results):
'''{{web_search_results}}'''

Available Document Details (empty if no documents):
'''{{doc_details}}'''

Valid xml tree with our reasons and decisions:
"""
        return web_search_prompt

    @property
    def web_search_prompt(self):
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""Your task is to generate web search queries for given question and conversation context.
You are given a question and conversation context as below. The current date is '{date}', year is {year}, month is {month}, day is {day}. 
Current question: 
'''{{context}}'''

Conversation context:
'''{{doc_context}}'''

Generate web search queries to search the web for more information about the current question. 
If the current question or conversation context requires a date, use the current date provided above. If it is asking for latest information or information for certain years ago then use the current date or the year provided above. 
{{pqs}}
Generate {{n_query}} well specified and diverse web search queries as a valid python list. 

Your output should look like a python list of strings like below example.
Valid python list of web search query strings:
["diverse google search query based on given document", "different_web_query based on the document and conversation", "search engine optimised query based on the question and conversation"]

Few examples are given below.
<example 1>
question:
'''What are the best ways to improve my health?'''

conversation context:
'''I am having bad sleep and feel tired a lot. Doctor suggested to drink lots of water as well.'''

Valid python list of web search query strings:
["how to improve health", "how does drinking more water help improve my body?", "how to improve health and sleep by drinking water and exercising", "Ways to improve cardiovascular health in {year}"]
</example 1>

# Note: Each web search query is different and diverse and focuses on different aspects of the question and conversation context.

<example 2>
question:
'''What are the recent developments in medical research for cancer cure?'''

conversation context:
'''I am working on a new painkiller drug which may help cancer patients and want to know what are the latest trends in the field. I can also use ideas from broader developments in medicine.'''

Valid python list of web search query strings:
["latest discoveries and research in cancer cure in {year}", "latest research works in painkiller for cancer patients in {year}", "Pioneering painkiller research works in {month} {year}.", "Using cancer cure for medical research in {year}"]
</example 2>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

<example 3>
question:
'''What are the emerging trends in AI and large language models?'''

conversation context:
'''I am working on a new language model and want to know what are the latest trends in the field. I can also use ideas from broader developments in AI.'''

Valid python list of web search query strings:
["latest discoveries and research in AI in {year}", "research works in large language models {month} {year}", "Pioneering AI research works which can help improve large language models.", "Using large language models for AI research in {year}"]
</example 3>

# Note: You can use the current date ({date}) and year ({year}) provided in the web search query.

Current question: 
'''{{context}}'''
Output only a valid python list of web search query strings for the current question.
Valid python list of web search query strings:
"""
        return web_search_prompt

    @property
    def web_search_question_answering_prompt(self):
        prompts = self.prompts
        return prompts["web_search_question_answering_prompt"]

    @property
    def get_more_details_prompt(self):
        prompts = self.prompts
        return prompts["get_more_details_prompt"]

    @property
    def document_search_prompt(self):
        prompts = self.prompts
        return prompts["document_search_prompt"]


prompts = CustomPrompts(os.environ.get("LLM_FAMILY", "gpt4"), os.environ.get("ROLE", "science"))



