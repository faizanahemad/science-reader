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

            persist_current_turn_prompt="""You are given conversation details between a human and an AI. You are also given a summary of how the conversation has progressed till now. 
Write a new summary of the conversation. Capture the salient, important and noteworthy aspects and details from the user query and system response. Your summary should be detailed, comprehensive and in-depth.
Capture all important details in your conversation summary including factual details, names and other details mentioned by the human and the AI. 
Preserve important details that have been mentioned in the previous summary especially including factual details and references while adding more details from current user query and system response.
Write down any special rules or instructions that the AI assistant should follow in the conversation as well.

The previous summary and salient points of the conversation is as follows:
'''{previous_summary}'''

Previous messages of the conversation are as follows:
'''{previous_messages_text}'''

The last 2 messages of the conversation from which we will derive the summary and salient points are as follows:
User query: '''{query}'''
System response: '''{response}'''

Write a summary of the conversation using the previous summary and the last 2 messages. Please summarize the conversation very informatively, in detail and depth.
Conversation Summary:
""",


            chat_slow_reply_prompt=f"""You are given conversation details between human and AI. We will be replying to the user's query or message given.
{self.date_string}
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
        rules = """
## Rules for writing code (especially code that needs to be executed and run) and making diagrams, designs and plots are given below inside <executable_code_and_diagramming_rules> </executable_code_and_diagramming_rules> tags.
<executable_code_and_diagramming_rules>
- Indicate clearly what python code needs execution by writing the first line of code as '# execute_code'. Write code that needs execution in a single code block.
- Write python code that needs to be executed only inside triple ticks (```)  write the first line of code as '# execute_code'. We can only execute python code.
- Write executable code in case user asks to test already written code, but ensure that it is safe code that does not delete files or have side effects. Write intermediate print statements for executable code to show the intermediate output of the code and help in debugging.
- When you are shown code snippets or functions and their usage example, write code that can be executed for real world use case, fetch real data and write code which can be used directly in production.
- When you write code that needs execution indicate that it needs to be executed by mentioning a comment within code which say "# execute_code". Write full and complete executable code within each code block even within same message since our code environment is stateless and does not store any variables or previous code/state.
- Write actual runnable code when code needs to be executed and convert any pseudo-code or incomplete code (or placeholder) to actual complete executable code with proper and full implementation on each line with proper comments. 
- You are allowed to read files from the input directory {input_directory} and write files to the directory {output_directory}.
- If asked to read files, only read these filenames from the input directory: {input_files}.
- You can use only the following libraries: pandas, numpy, scipy, matplotlib, seaborn, scikit-learn, networkx, pydot etc.

- Certain diagrams can be made using mermaid js library as well. First write the mermaid diagram code inside <pre class="mermaid"> and </pre> tags.
- When you make plots and graphs, save them to the output directory with filename prefix as {plot_prefix} and extension as jpg.
- You can also make diagrams using mermaid js library. You can make Flowcharts, Sequence Diagrams, Gantt diagram, Class diagram, User Journey Diagram, Quadrant Chart, XY Chart. Write the diagram code inside <pre class="mermaid"> and </pre> tags so that our mermaid parser can pick it and draw it.
- You are allowed to make diagrams using draw.io or diagrams.net xml format. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```).
- Use draw.io or diagrams.net to make diagrams like System design diagrams, complex scientific processes, flowcharts, network diagrams, architecture diagrams etc. Always Write the draw.io xml code inside triple ticks like (```xml <Drawio xml code> ```). so that our drawio parser can pick it and draw it.
- Make high quality plots with clear and extensive labels and explanations. Always save your plots to the directory {output_directory} with filename prefix as {plot_prefix}.

- Write code with indicative variable names and comments for better readability that demonstrate how the code is trying to solve our specific use case.
- Code in python and write code in a single cell for code execution tasks.
- Write full and complete executable code since our code environment is stateless and does not store any variables or previous code/state.
- You are allowed to write output to stdout or to a file (in case of larger csv output) with filename prefix as {file_prefix}.
- Convert all pandas dataframe data to pure numpy explicitly before using libraries like scikit-learn, matplotlib and seaborn plotting. Remember to convert the data to numpy array explicitly before plotting.
- Remember to write python code that needs to be executed with first line comment as '# execute_code'. We can only execute python code. Write intermediate print statements for executable code to show the intermediate output of the code and help in debugging.
- Ensure that all data is converted to numpy array explicitly before plotting in python. Convert DataFrame columns to numpy arrays for plotting.
- Allowed to read csv, excel, parquet, tsv only.
- Do not leak out any other information like OS or system info, file or directories not permitted etc. Do not run system commands or shell commands.
- Do not delete any files.
- Do not use any other libraries other than the ones mentioned above.
</executable_code_and_diagramming_rules>
""" + f"\n- {self.date_string}\n"
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

        prompt = f"""You are an expert AI system which determines whether our search results are useful and can answer a user query or not. If our search results can't answer the user query satisfactorily then you will decide if we need to do more web search and write two new web search queries for performing search again.
If our search results answer the query nicely and satisfactorily then <answered_already_by_previous_search> will be yes. If our search queries are sensible and work well to represent what should be searched then <answered_already_by_previous_search> will be yes. 
Usually our searches work well and we don't need to do more web search and <web_search_needed> will be no. Decide to do further web search only if absolutely needed and if our queries are not related or useful for user message. Mostly put <web_search_needed> as no.
{self.date_string} 

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

# Note: You can use the current date ({date}) and year ({year}) in the web search queries that you write. If our search queries are sensible and correct for user message and work well to represent what should be searched then <answered_already_by_previous_search> will be yes and <web_search_needed> will be no.

Output Template for our decision planner xml is given below.
<planner>
    <thoughts>Your thoughts in short on whether the previous web search queries and previous web search results are sufficient to answer the user message written shortly.</thoughts>
    <answered_already_by_previous_search>no</answered_already_by_previous_search>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_queries>
        <query>web search query 1</query>
        <query>web search query 2 with year ({year}) or date ({date}) if needed</query>
    </web_search_queries>
</planner>

<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.

planner xml template if the user query is already answered by previous search:
<planner>
    <thoughts>Your thoughts on how the web search queries and previous web search results are sufficient to answer the user message.</thoughts>
    <answered_already_by_previous_search>yes</answered_already_by_previous_search>
    <web_search_needed>no</web_search_needed>
    <web_search_queries></web_search_queries>
</planner>

Write your output decision in the above planner xml format.
"""
        return prompt, parse_llm_output

    @property
    def date_string(self):
        import datetime
        import calendar
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        weekday = datetime.datetime.now().weekday()
        weekday_name = calendar.day_name[weekday]
        time = datetime.datetime.now().strftime("%H:%M:%S")
        return f"The current date is '{date}', year is {year}, month is {month}, day is {day}. It is a {weekday_name}. The current time is {time}."

    @property
    def planner_checker_prompt_explicit(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        year = datetime.datetime.now().strftime("%Y")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}
Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Planner rules:
- Inside need_finance_data tag, you will write yes if the user message needs finance data, stocks data or company data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
- Inside need_diagram tag, you will write yes if a diagram is asked explicitly in the user message. This will be needed if user has explicitly asked us to draw a diagram or plot or graph or show something that can be shown via drawing/charting/plotting/graphing/visualization.
- Inside code_execution tag, you will write yes if python code execution or data analysis or matplotlib/seaborn is asked explicitly in the user message. Code execution is needed when user asks data analysis results or plotting or diagraming of specific types with python. This will be needed if user has explicitly asked us to write python code.
- Inside code_execution tag, you will write no if user has asked for code but did not ask to execute the code or user did not ask for data analysis or python plotting.
- Inside web_search_needed tag, you will write yes if asked explicitly for web search or google search in the user message. This will be needed if user has explicitly asked us to do web search. If user has not asked for web search then put web search needed as no.
- Inside read_uploaded_document tag, you will write yes if we need to read any uploaded document given under 'Available Document Details' to answer the user query. This will be needed if user has uploaded a document relevant to this current user message and we need to read that particular document to answer the query.
- When user wants to refer to a particular document themselves they write as 'refer to document #doc_id' or 'refer to document titled "title of document"'. For example - "Summarise #doc_1" means we need to read the uploaded #doc_1 and summarise it. So read_uploaded_document will be yes, and within document_search_queries we will write <document_query><document_id>#doc_1</document_id><query>Summarise this document.</query></document_query>.
- User may also refer to uploaded docs by title or by their short names. Look at Previous User Messages as well to understand if current user message refers to any document in a hidden way.
- Sometimes the user may have referred to document title or document id as #doc_id in previous messages instead of the current user message. Infer the document id or title from the previous messages and write the document id or title in the document_query.
Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_type>general/academic</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given user message with year ({year}) if recent results are important.</query>
        <query>different_web_query based on the user message and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty and not needed in the planner xml at all if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.
<web_search_type> will not be needed in the planner xml if web search is not needed.
Example of how planner xml looks like if both web search is not needed and document search is not needed.
<planner>
    <domain>Identified Domain</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>no</web_search_needed>
    <read_uploaded_document>no</read_uploaded_document>
</planner>

Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. Include year and date in web search query if it needs recent, up to date or latest information.
<need_finance_data> will be yes if user message needs finance historical data, stocks historical data or stock market daily data like price and volume or company financial and quarterly/annual reports data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
<need_finance_data> will be no if it is a finance question but doesn't need any finance data or stock market data to answer the query, like asking for book recommendations or asking for finance concepts or definitions, doesn't need finance data so <need_finance_data> will be no.
<read_uploaded_document> could be yes if this current user message or any previous user message refers to an uploaded document and current message is asking indirectly about the uploaded document with phrases like "how does the work ... " or "what are their unqiue contributions?" etc. Here you need to infer document id or title from the previous messages and write the document id in the document_query.
List of possible domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Stock Market, Trading & Investing
- Mathematics
- QnA
- AI
- Software


Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not under read_uploaded_document.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
"""
        return web_search_prompt

    @property
    def planner_checker_prompt_short(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message and then answers the user's message if needed by themselves. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}

Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Planner rules:
- Inside need_finance_data tag, you will write yes if the user message needs finance data, stocks data or company data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
- Inside need_diagram tag, you will write yes if a diagram is needed for clear explanation or asked explicitly in the user message. This will be needed for questions which need a diagram for clear explanation or if user has explicitly asked us to draw a diagram or plot or graph.
- Inside code_execution tag, you will write yes if python code execution or data analysis or matplotlib/seaborn is really needed or asked explicitly in the user message. Data analysis and plotting may also be needed for finance data use cases or when user asks plotting or diagramming of specific types with python. This will be needed for questions which need python code execution or data analysis or matplotlib plot or if user has explicitly asked us to write python code.
- Inside code_execution tag, you will write no if user has asked for code or about python code but we don't need to execute code to answer the user query.
- Inside web_search_needed tag, you will write yes if web search is needed for clear explanation or asked explicitly in the user message. This will be needed for questions which need web search for clear explanation, or questions needs recent updated information or if user has explicitly asked us to do web search. Web search takes extra time and user has to wait for the answer so if an LLM or you can answer well without web search then put web search needed as no.

Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>yes/no</web_search_needed>
    <web_search_type>general/academic</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given user message with year ({year}) if recent results are important.</query>
        <query>different_web_query based on the user message and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty and not needed in the planner xml at all if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed, and not needed in the planner xml at all.
<web_search_type> will not be needed in the planner xml if web search is not needed.
Example of how planner xml looks like if both web search is not needed and document search is not needed.
<planner>
    <domain>Identified Domain</domain>
    <need_finance_data>yes/no</need_finance_data>
    <need_diagram>yes/no</need_diagram>
    <code_execution>yes/no</code_execution>
    <web_search_needed>no</web_search_needed>
    <read_uploaded_document>no</read_uploaded_document>
</planner>

web_search will usually be yes if we have not done any web search previously or if the question is looking for latest information that an LLM can't answer. For programming framework help or general knowledge questions we may not need to do web search always but for frameworks or programming questions where we are not certain if you can answer by yourself then perform web search.
Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. Include year and date in web search query if it needs recent, up to date or latest information.
We keep important factual information in short form in our memory pad. use_memory_pad will be yes if we need to use some information from the memory pad for better answering. This will generally be needed for questions which need facts to answer them and those facts are part of our conversation earlier.
<need_finance_data> will be yes if user message needs finance historical data, stocks historical data or stock market daily data like price and volume or company financial and quarterly/annual reports data to answer the query. This will be needed for questions which need financial data or stock market or historical market data or company financial results or fund house data to answer them.
<need_finance_data> will be no if it is a finance question but doesn't need any finance data or stock market data to answer the query, like asking for book recommendations or asking for finance concepts or definitions, doesn't need finance data so <need_finance_data> will be no.

List of possible domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Stock Market, Trading & Investing
- Mathematics
- QnA
- AI
- Software


Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
"""
        return web_search_prompt

    @property
    def planner_checker_prompt(self):
        # TODO: Fire web search and document search prior to planner for speed.
        import datetime
        date = datetime.datetime.now().strftime("%d %B %Y")
        year = datetime.datetime.now().strftime("%Y")
        month = datetime.datetime.now().strftime("%B")
        day = datetime.datetime.now().strftime("%d")
        web_search_prompt = f"""You are an expert AI assistant who decides what plan to follow to best answer to a user's message and then answers the user's message if needed by themselves. You are able to determine which functions to call (function calling and tool usage) and what plan to use to best answer a query and help an user.
{self.date_string}

Now based on given user message and conversation context we need to decide a plan of execution to best answer the user's query in the planner xml format given below.

Your output should look be a valid xml tree with our plan of execution like below example format.
<planner>
    <domain>Science</domain>
    <is_question_about_finance_stocks_mutual_fund_etf>yes/no<is_question_about_finance_stocks_mutual_fund_etf>
    <company_stock_fund_etf_name>company_ticker</company_stock_fund_etf_name>
    <is_diagram_needed_for_clear_explanation_or_asked_explicitly>yes/no</is_diagram_needed_for_clear_explanation_or_asked_explicitly>
    <suggested_diagram_type>
        <diagram_type>What type of diagram best explains what is asked or needed by user.</diagram_type>
        <drawing_library>Which Library from among mermaid js, draw.io (diagrams.net) xml, or python matplotlib/seaborn code is to be used</drawing_library>
    </suggested_diagram_type>
    <python_code_execution_or_data_analysis_or_matplotlib_needed_or_asked_explicitly>yes/no</python_code_execution_or_data_analysis_or_matplotlib_needed_or_asked_explicitly>
    <use_memory_pad>no</use_memory_pad>
    <web_search_needed_for_clear_explanation_or_asked_explicitly>yes/no</web_search_needed_for_clear_explanation_or_asked_explicitly>
    <web_search_type>general</web_search_type>
    <web_search_queries>
        <query>diverse google search query based on given document</query>
        <query>different_web_query based on the document and conversation</query>
        <query>search engine optimised query based on the question and conversation</query>
        <query>search query based on the question and conversation</query>
    </web_search_queries>
    <read_uploaded_document>yes/no</read_uploaded_document>
    <document_search_queries>
        <document_query><document_id>#doc_2</document_id><query>What is the methodology</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the results</query></document_query>
        <document_query><document_id>#doc_3</document_id><query>What are the datasets used?</query></document_query>
    </document_search_queries>
</planner>

<document_search_queries> will be empty if no documents are uploaded or no documents need to be read.
<web_search_queries> will be empty if no web search is needed.
web_search will usually be yes if we have not done any web search previously or if the question is looking for latest information that an LLM can't answer. For programming framework help or general knowledge questions we may not need to do web search always but for frameworks or programming questions where we are not certain if you can answer by yourself then perform web search.
Web search type can be general or academic. If the question is looking for general information then choose general web search type. If the question is looking for academic or research papers then choose academic as web search type.
Generate 4 well specified and diverse web search queries if web search is needed. 
We keep important factual information in short form in our memory pad. use_memory_pad will be yes if we need to use some information from the memory pad for better answering. This will generally be needed for questions which need facts to answer them and those facts are part of our conversation earlier.

Possible Domains:
- None
- Science
- Arts
- Health
- Psychology
- Finance
- Mathematics
- QnA
- AI
- Software

Choose Domain as None if the user message query doesn't fit into any of the other domains.
{{permanent_instructions}}

If we have any documents uploaded then you will be given the document id, title and context so that you can decide if we need to read the document or not.
Available Document Details (empty if no documents are uploaded, for read_uploaded_document is
'''{{doc_details}}'''

Conversation context and summary:
'''{{summary_text}}'''

Previous User Messages:
'''{{previous_messages}}'''


Current user message: 
'''{{context}}'''

Valid xml planner tree with our reasons and decisions:
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
You are given a question and conversation context as below. {self.date_string} 
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

import xml.etree.ElementTree as ET


def xml_to_dict(xml_string):
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return "Invalid XML: Check if every opening tag has a corresponding closing tag."

    def parse_element(element):
        # Check if element has text content and is not None
        if element.text is not None:
            text = element.text.strip()
            # Convert yes/no to Boolean
            if text.lower() in ["yes", "no", "true", "false"]:
                return text.lower() == "yes" or text.lower() == "true"
                # Try converting text to float or int if possible
            try:
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return text
        else:
            # Return None if element has no text content
            return None

    def parse_list_elements(element):
        # Parse elements that should be lists
        result = []
        for subchild in element:
            if subchild.tag == "document_query":
                sub_result = {}
                for item in subchild:
                    sub_result[item.tag] = parse_element(item)
                result.append(sub_result)
            else:
                result.append(parse_element(subchild))
        return result

    def parse_nested_elements(element):
        # Parse nested elements and return a dictionary
        return {subchild.tag: parse_element(subchild) for subchild in element}

    result_dict = {}
    for child in root:
        if child.tag in ["web_search_queries", "document_search_queries"]:
            result_dict[child.tag] = parse_list_elements(child)
        elif child.tag == "suggested_diagram_type":
            result_dict[child.tag] = parse_nested_elements(child)
        else:
            result_dict[child.tag] = parse_element(child)

    return result_dict
