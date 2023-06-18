@timer
def call_easy_model(completion_models, model, text, temperature, system):

    if model in completion_models:
        input_len = len(davinci_enc.encode(text))
        assert 4000 - input_len > 0
        completions = openai.Completion.create(
            engine=model,
            prompt=text,
            temperature=temperature,
            max_tokens = 4000 - input_len,
        )
        message = completions.choices[0].text
        finish_reason = completions.choices[0].finish_reason
#                 if finish_reason != 'stop':
#                     print(easy_model + " " + str(input_len) + " " + str(len(self.easy_enc.encode(message))) + " " + " "+ finish_reason + " " + message + " \n")
        assert finish_reason == 'stop'
    else:
        input_len = len(easy_enc.encode(text))
        assert 4000 - input_len > 0
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": text},
                ],
                temperature=temperature
            )
        message = response['choices'][0]['message']['content']
        finish_reason = response['choices'][0]['finish_reason']
#                 print(easy_model + " " + str(len(self.easy_enc.encode(self.system +" \n " + text))) + " " + str(len(self.easy_enc.encode(message))) + " " + " "+ finish_reason + " " + message + " \n")
        assert finish_reason == 'stop'
    return message

class CallGpt:
    def __init__(self, ):
        easy_models = [
            "text-davinci-003", "gpt-3.5-turbo", "gpt-3.5-turbo-0301", "text-davinci-003", 
            "text-davinci-002", 
#             "davinci-instruct-beta:2.0.0", 
#             "text-davinci-001"
                                       ]
        self.easy_models = round_robin(random.sample(easy_models, len(easy_models)))
        self.completion_models = [
            "text-davinci-003","text-davinci-002", "davinci-instruct-beta:2.0.0", "text-davinci-001"
        ]
        turbo_models = ["gpt-3.5-turbo", "gpt-3.5-turbo-0301"]
        turbo_models = random.sample(turbo_models, len(turbo_models))
        self.turbo_models = round_robin(turbo_models)
        hard_models = ["gpt-4", "gpt-4-0314"]
        hard_models = random.sample(hard_models, len(hard_models))
        self.hard_models = round_robin(hard_models)

        self.system = "You are a helpful assistant. Please respond to the user request while following their instructions."
        import tiktoken
        self.easy_enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        self.hard_enc = tiktoken.encoding_for_model("gpt-4")
        

    def get_easy_call(self):
        @retry(wait=wait_random_exponential(min=30, max=60), stop=stop_after_attempt(3))
        def call(text, temperature=0.7, num_tokens=None):
            easy_model = next(self.easy_models)
            try:
                return call_easy_model(self.completion_models, easy_model, text, temperature, self.system)
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                easy_model = next(self.easy_models)
                return call_easy_model(self.completion_models, easy_model, text, temperature, self.system)
        return call
    
    
    def get_turbo_call(self):
        @retry(wait=wait_random_exponential(min=30, max=90), stop=stop_after_attempt(3))
        def call(text, temperature=0.7, num_tokens=None):
            easy_model = next(self.turbo_models)
            input_len = len(self.easy_enc.encode(self.system +" \n " + text))
            
            response = openai.ChatCompletion.create(
                model=easy_model,
                messages=[
                        {"role": "system", "content": self.system},
                        {"role": "user", "content": text},
                    ],
                    temperature=temperature
                )
            message = response['choices'][0]['message']['content']
            finish_reason = response['choices'][0]['finish_reason']
            assert finish_reason == 'stop'
            return message
        return call
    
    def get_hard_call(self):
        @retry(wait=wait_random_exponential(min=30, max=90), stop=stop_after_attempt(3))
        def call(text, temperature=0.1, num_tokens=None):
            model = next(self.hard_models)
            response = openai.ChatCompletion.create(
                model=model,
                messages=[
                        {"role": "system", "content": self.system},
                        {"role": "user", "content": text},
                    ],
                    temperature=temperature
                )
            assert response['choices'][0]['finish_reason'] == 'stop'
            return response['choices'][0]['message']['content']
        return call
    
    
    def get_streaming_turbo_call(self):
        print("Get GPT Turbo call")
        @retry(wait=wait_random_exponential(min=30, max=90), stop=stop_after_attempt(3))
        def call(text, temperature=0.7, num_tokens=None):
            easy_model = next(self.turbo_models)            
            try:
                for c in call_chat_model(easy_model, text, temperature, self.system):
                    yield c
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                easy_model = next(self.turbo_models)
                for c in call_chat_model(easy_model, text, temperature, self.system):
                    yield c
        return call
    
    def get_streaming_hard_call(self):
        print("Get GPT 4 call")
        @retry(wait=wait_random_exponential(min=30, max=90), stop=stop_after_attempt(3))
        def call(text, temperature=0.1, num_tokens=None):
            model = next(self.hard_models)
            try:
                for c in call_chat_model(model, text, temperature, self.system):
                    yield c
            except Exception as e:
                if type(e).__name__ == 'AssertionError':
                    raise e
                model = next(self.hard_models)
                for c in call_chat_model(model, text, temperature, self.system):
                    yield c
        return call

class DecisionMakerTool:
    def __init__(self):
        self.name = "DecisionMakerTool"
        self.description = """
DecisionMakerTool:
    This tool helps in making decisions. If you have some alternative action choices, based on some context or prior information and need to make a decision where decision can be a choice from set of options, then this tool is useful. This DecisionMakerTool is especially useful if the decision or choice cannot be made using python if-else but rather needs language support and more nuanced intelligence and world knowledge. Can also be used as a multi-choice reading comprehension QnA tool.

    Input params/args: 
        context (str): Context on which decision/choice is to be made.
        options (str): str representating options in format of `<option_number>: <option_name>` for each option, separated by commas.

    Returns: 
        dict: {"choice_reason": <str, reason of making the choice, pros and cons, other thoughts>, "choosen_option": <choosen option as int>}

    Usage:
        `choice_decision = DecisionMakerTool()(context="Should a person stay awake at night.", options=["1: No, 2: Yes"]) # Note: this tool needs to be initialized first.`
        `choice_decision = DecisionMakerTool()(context="You are given two stories about a monk who had to survive starvation below. first story: {story_1} , second story:  {story_2}, choose the story which best motivates a person suffering from starvation.", options=["1: first story, 2: second story"])`

    """
        
        self.prompt = PromptTemplate(
            input_variables=["context", "options"],
            template="""
You are a helpful decision making tool. Your responsibility is to make a decision (from a set of options) given some query/context and a set of options. You will give a single number output that signifies your decision for the query/context.

The context for which you need to make a decision or choose an option is given below:

{context}

The options you can take is given below in format of `<option_number>: <option_name>` for each option, separated by commas:

{options}

Choose one option from the given options (a single number) and also provide a reason for your choice. 
Your answer is a python dictionary which has two keys (choice_reason: <str, option number and then reason of making the choice, why this particular option over other options, pros and cons, other thoughts> and choosen_option: <choosen option as int>).
Just output a python dict with these two keys (choice_reason and choosen_option) and their values only.


""",
        )
        
    def __call__(self, context, options):
        prompt = self.prompt.format(context=context, options=options)
        return eval(callGpt.get_turbo_call()(prompt, temperature=0))
    

class CallLargeLanguageModelWithInstructionsTool:
    def __init__(self):
        self.name = "CallLargeLanguageModelWithInstructionsTool"
        self.description = """
CallLargeLanguageModelWithInstructionsTool:
    This tool takes instructions and some data and passes them on to a Large Language Model for further processing. It can do language oriented tasks like summarization, question-answer, question-generation, etc, it cannot do web-search, mathematics and other non-language oriented tasks. Limitation- This tool can only generate or write only 2000 words at one time. It also has input length limit, where it can only take 2000 words at a time. Giving this tool more than 2000 words in either `instructions` or `data` will result in error.

    Input params/args: 
        instructions (str): instructions to the language model on what to do with given data dictionary.
        data (dict): data dictionary which language model uses along with instructions to produce some useful result. (Optional)

    Returns: 
        str: model_result (model_result is less than 2000 words always)

    Usage:
        `model_result = CallLargeLanguageModelWithInstructionsTool()(instructions="instructions to language model", data=<data_dictionary for using in format string of instruction>) # Note: this tool needs to be initialized first. # model_result is less than 2K words always`
        `dog_owner_name_text = CallLargeLanguageModelWithInstructionsTool()(instructions="get the name of the owner of dog from the sentence: {text}", data={"text": "the pretty brown dog was owned by Mr. Miles"}) # length of instructions + data should be less than 2K words always`

    """
    def __call__(self, instructions, data=dict()):
        try:
            prompt = instructions.format(**data)
        except:
            prompt = instructions + " \n\n Data for following instructions in python dictionary format: \n\n " + str(data)
        return callGpt.get_turbo_call()(prompt, temperature=0.3)
    
    
    
class ContextualSummarizer(ContextualReader):
    def __init__(self):
        super().__init__()
        self.name = "ContextualSummarizer"
        self.description = """
ContextualSummarizer:
    Similar to Contextual_Reader, but guarantees much smaller text outputs due to summarisation of inputs. This tool takes a context/query/instruction, and a text document. It summarises the document based on the context/query/instruction and outputs only parts of document relevant to user query. Very Useful when the contextual document is too long and you need to store a short contextual version of it.

    Input params/args: 
        context_user_query (str): instructions or query on how to read the document to provide summary from the document.
        text_document (str): document to read and sumarize from using context_user_query.

    Returns: 
        str: summary_from_document

    Usage:
        `summary_from_document = ContextualSummarizer()(context_user_query="instructions on how to read document", text_document="document to summarize") # Note: this tool needs to be initialized first.`

    """
        self.prompt = PromptTemplate(
            input_variables=["context", "document"],
            template="""
You are given a context/instruction which specifies what is needed and any other specific instructions as below \n
{context}

Next, you are also given a document which you have to read and gather more context and information to answer the question/instruction. 
Remember you don't need to answer the user's question now, you just need to gather more information which could possibly help in answering the user's question from this document given.
Gather the information in a concise way like a scientist, not like a novelist. Ensure to provide short, point wise, summarised version, we intend the output to be small but still capture all details pertaining to "{context}".
Document is given below:
{document}
""",
        )
        

class FuseInformation:
    def __init__(self,):
        self.name = "FuseInformation"
        self.description = """
FuseInformation:
    This tool takes a context/query/instruction, and two text documents, it then reads the two documents based on the context or query instruction and outputs only parts of the documents relevant to context/instruction. Useful when you have multiple documents and their combined length is too long and you need to store a short contextual version of both documents. Limitation - This tool can only generate or write only 2000 words at one time.

    Input params/args: 
        context_user_query (str): instructions or query on how to read the documents and fuse them.
        first_document (str): first document to read.
        second_document (str): second document to read.

    Returns: 
        str: fused_content_both_documents

    Usage:
        `fused_content_both_documents = FuseInformation()(context_user_query="instructions on how to read document", first_document="first document to read", second_document="second document to read") # Note: this tool needs to be initialized first.`

    """
        
        self.prompt = PromptTemplate(
            input_variables=["context", "first_document", "second_document"],
            template="""
You are given a request/context/query which specifies what needs to be done and any other specific instructions as below \n
{context}

Next, you are also given a two documents which you have to read and gather more context and information to answer the question. 
Remember you don't need to answer the user's question now, you just need to gather more information which could possibly help in answering the user's question from this document given.
Also remember to read both documents and find relevant information from both of them.
Documents are given below:
First Document:
{first_document}

\n\n
Second Document:
{second_document}
""",
        )
    def __call__(self, context_user_query, first_document, second_document):
        prompt = self.prompt.format(context=context_user_query, first_document=first_document, second_document=second_document)
        return callGpt.get_hard_call()(prompt, temperature=0.2)
        
    
class ContextualAnswer:
    def __init__(self):
        self.name = "ContextualAnswer"
        self.description = """
ContextualAnswer:
    This tool takes a context/query/instruction, and one text document, it then reads the document based on the context/query/instruction and provides an answer to the query/instruction using the document and its own knowledge. If no information/answer is found on requested query it says "no answer" in output.

    Input params/args: 
        context_user_query (str): instructions or query on how to read the document to provide an answer from the document.
        text_document (str): document to read and answer from.

    Returns: 
        str: answer

    Usage:
        `answer = ContextualAnswer()(context_user_query="instructions on how to read document and answer", text_document="document to read") # Note: this tool needs to be initialized first.`

    """
        
        self.prompt = PromptTemplate(
            input_variables=["context", "document"],
            template="""
You are given a context/instruction/query which specifies what is needed and any other specific instructions as below \n

{context}

Next, you are also given a document which has some context which can help in answering the query or help find the right information.
Remember if you can't answer the question given your own knowledge and the document, say that you can't answer.
You can use the provided document as a support for your answer but you can also use your own prior knowledge. 
Answer the query based on the document and usually keep answers `short` unless asked to `elaborate`. If no information/answer is found on requested query say "no answer" in your output.
Document is given below:
{document}

Answer:

""",
        )
    def __call__(self, context_user_query, text_document):
        prompt = self.prompt.format(context=context_user_query, document=text_document)
        return callGpt.get_turbo_call()(prompt, temperature=0.2)
    
class ExtractInformationTool:
    def __init__(self):
        self.name = "ExtractInformationTool"
        self.description = """
ExtractInformationTool:
    This tool takes a context/query/instruction, and one text document, it then reads the document based on the context/query/instruction and extracts a single piece of information. If no information/answer is found on requested query it says "no answer" in output. To use this tool ask it pin pointed (not vague) questions (e.g. if you need bottle capacity, ask - "capacity in litres" not "size of the bottle",). Another rule is to ask just for one ( or a single piece of ) information (e.g. don't ask for name and place in same Tool call, if you need two pieces of information, call the tool twice with separate query each time).

    Input params/args: 
        context_user_query (str): instructions or query on what information to extract from document.
        text_document (str): document to read and extract information.

    Returns: 
        str: answer

    Usage:
        `answer = ExtractInformationTool()(context_user_query="instructions on how to read document and extract a single piece of information", text_document="document to read") # Note: this tool needs to be initialized first.`

    """
        
        self.prompt = PromptTemplate(
            input_variables=["context", "document"],
            template="""
You are given a context/instruction/query which specifies what is needed and any other specific instructions as below \n
{context}

Next, you are also given a document which has some context which can help in answering the query or help find the right information.
You need to extract the information from the provided document only. 
Usually the extracted information should be very short (one word or few word answers are preferred). 
If you are asked a number just give the number, if you are asked a name, just give the name, in general just the information or answer, no platitudes or preambles. 
Example: if answer is "The number of people on train is 67" -> just output "67".
If no information/answer is found on requested query say "no answer" in your output.
Document is given below:
{document}

""",
        )
    def __call__(self, context_user_query, text_document):
        prompt = self.prompt.format(context=context_user_query, document=text_document)
        return callGpt.get_turbo_call()(prompt, temperature=0.2)


class QuestionGeneration:
    def __init__(self):
        self.name = "QuestionGeneration"
        self.description = """
QuestionGeneration:
    This tool takes a text document and summarizes it into a shorter version while preserving the main points and context. Useful when the document is too long and needs to be shortened before further processing.

    Input params/args: 
        long_document (str): document to summarize.

    Returns: 
        str: summarized_document.

    Usage:
        `summary = LongSummarizer()(text_document="document to summarize") # Note: this tool needs to be initialized first.`
    """
        
        self.prompt = PromptTemplate(
            input_variables=["document"],
            template="""Write as many valid and important question-answer pairs as can be answered/derived from the document below:
{document}

Separate the question-answer pairs by newline \\n and also put each question and answer in a newline.

Questions and Answers:

""",
        )
        
    def __call__(self, document):
        prompt = self.prompt.format(document=document)
        try:
            resp = call_ai21(prompt, temperature=0.5)
            resp = resp.split('\n')
            assert len(resp)%2==0
        except:
            resp = call_ai21(prompt, temperature=0.4)
            resp = resp.split('\n')
            assert len(resp)%2==0
        resp = concat_array_two_at_a_time(resp)
        return resp
    
class DeepReader:
    def __init__(self, chunk_size=3000):
        self.chunk_size=3000
        self.name = "DeepReader"
        self.description = """
DeepReader:
    This tool reads the paper in depth.

    Input params/args: 
        long_document (str): document to generate questions.
        full_summary_doc (dict): summary dict from LongSummarizer

    Returns: 
        Dict[str, str]: deep reading dict

    Usage:
        `deep_read = DeepReader()(long_document="long text document", full_summary_doc=<full_summary from LongSummarizer>) # Note: this tool needs to be initialized first.`
    """
        self.answer_format = """
{
    "methodology": "",
    "previous_literature_and_differentiation": "",
    "experiments_and_evaluation": "",
    "results_and_comparison": "",
    "limitations_and_future_work": ""
}
        """
        self.prompt = PromptTemplate(
            input_variables=["full_summary", "document", "answer_format", "previous_information"],
            template="""
We are reading a paper / document in parts and trying to various aspects of the work.
Given below text is small part/fragment text of the larger document that we are reading sequentially.
"{document}"

Note: This is a raw unformatted document which may contain irrelevant text/syntax or other noise. Ignore what you consider noise or irrelevant.


You are given a summary of the full larger document below:
"{full_summary}"


Based on these information you are requested to provide the below information (or add more to already gathered "previous sections information") to help understand this work/document better.

- Motivation and Methodology (in "methodology" field)
    - What do the authors do in this overall work (i.e. their methodology) with details from this part/fragment 
    - Detailed methodology and approach described in this work.
    - what problem they address ?
    - how they solve the problem in details?
    - Why do they solve this problem?
    - what is their justification in doing it? Why do they use this method? 
    - Any insights from their methods

- Previous Literature and Background work (in "previous_literature_and_differentiation" field)
    - what previous literature is referred to?
    - how their work is different from previous literature?
    
- Experiments and Evaluation (in "experiments_and_evaluation" field)
    - How is the proposed method/idea evaluated
    - on what datasets do they evaluate
    - What experiments are performed?
    - Are there any experiments with surprising insights?
    - Any other surprising experiments or insights
    
- Results (in "results_and_comparison" field)
    - What results do they get and 
    - how does this method perform compared to other methods?
    
- Limitations (in "limitations_and_future_work" field)
    - What are the limitations of this method, 
    - where does this method fail? 
    - What are some further future research opportunities for this domain as a follow up to this method?

Guidelines:
- We may have some of these fields from previous sections as well. Don't repeat the information we already have in your output. 
- If there is new information for these fields from the current section, then just output the new information from this section to the respective field.
- Be concise but detailed and informative, capture all information, don't use platitudes.
- Provide detailed answers for each field with as much information as possible. Don't miss out any information.
- Avoid phrases like "This fragment serves as", "This fragment highlights", "This fragment demonstrates", "In this fragment, ", "In this work" etc in your output. We are reading the larger document in small parts due to system limitation but all the output will be concatenated together before showing to the user, hence these phrases serve no purporse.

If this is not the first section, then from previous sections we have gathered the below "previous sections information":
"{previous_information}"

In case this is first section, then "previous sections information" will be empty else it will be in the output python dictionary format.


Your answer/output must only be a python dictionary only of below format:

{answer_format}

""",
        )
    def __call__(self, long_document, full_summary):
        
        chunks = ChunkText(long_document, self.chunk_size)
        fsum = full_summary["running_summary"]
        all_sections_data = []
        prev = {}
        for chunk in tqdm(chunks):
            prompt = self.prompt.format(full_summary=fsum, document=chunk, answer_format=self.answer_format, previous_information=str(prev))
            answer = callGpt.get_hard_call()(text=prompt, temperature=0.9)
            print(answer)
            answer = eval(answer)
            prev = answer
            all_sections_data.append(answer)
            prev = {k: " ".join([d[k] for d in all_sections_data]).strip() for k in list(all_sections_data[0].keys())}
            
        return all_sections_data


class QuestionAnswerGenerator:
    def __init__(self, chunk_size=1000):
        self.chunk_size=1000
        self.name = "QuestionAnswerGenerator"
        self.description = """
QuestionAnswerGenerator:
    This tool generates questions for chunks of the text document.

    Input params/args: 
        long_document (str): document to generate questions.
        full_summary_doc (dict): summary dict from LongSummarizer

    Returns: 
        List[Tuple[str]]: questions and answers for each chunk.

    Usage:
        `questions_and_answers = QuestionAnswerGenerator()(long_document="long text document", full_summary_doc=<full_summary from LongSummarizer>) # Note: this tool needs to be initialized first.`
    """
        self.prompt = PromptTemplate(
            input_variables=["full_summary", "current_section", "next_section", "previous_section",  
                             "previous_questions_and_answers"],
            template=""" 
We want to generate questions and answers from current given section/fragment/chunk of a larger work document. 
The summary of the larger document is given below:
{full_summary}

The previous section is given below:
"{previous_section}"

The current section/fragment is given below:
"{current_section}"

The next section is given below:
"{next_section}"


We also provide a set of questions and answers we had earlier created from the current section below:
{previous_questions_and_answers}

Based on these information you are requested to generate further questions and answers to help understand this work deeper.
Generate the following type of questions and their answers.
- Complex Questions and answers which help in deeply understanding this work.
- Questions which will help a scientist/researcher understand this work.
- Questions which will help a scientist to use this work document for their own stuff.
- Thought provoking questions which can be opinionated
- Questions which require knowledge of multiple sections and reading of whole document.
- Questions regarding criticisms and short comings and debatable decisions made in this work.

Guidelines to follow:
- Ensure that your answers are long, elaborate, detailed and provide deeper insights. 
- Ensure that your questions are complex and difficult to answer.
- No short answers.
- Generate each question and answer in a separate line.

Questions and Answers:

""",
        )
    def __call__(self, long_document, full_summary):
        
        chunks = full_summary["chunks"]
        fsum = full_summary["running_summary"]
        long_sum = full_summary["full_length_summary"] # "expanded_summary"
        previous_questions_and_answers = full_summary["chunk_questions"]
        
        prompts = []
        for ix, (pqa, chunk) in enumerate(zip(previous_questions_and_answers, chunks)):
            previous_section = "No previous section. We are on first section." if ix == 0 else chunks[ix - 1]
            next_section = "No next section. We are on last section." if ix == len(chunks)-1 else chunks[ix + 1]
            prompt = self.prompt.format(full_summary=fsum, current_section=chunk, 
                                        previous_section=previous_section, next_section=next_section, 
                                        previous_questions_and_answers=pqa)
            prompts.append(prompt)
        def printed_gpt_call(**kwargs):
            rsp = callGpt.get_turbo_call()(**kwargs)
#             print(rsp)
            return rsp
        calls = [{"text": p, "temperature": 0.7, "num_tokens": 4000} for p in prompts]
        responses = call_api_parallel(calls, printed_gpt_call, max_workers=2)
        chunk_questions = []
        for ix, (qna_resp, call) in enumerate(zip(responses, calls)):
            qna_success = False
            while not qna_success:
                qna = [qa.strip() for qa in qna_resp.split("\n") if len(qa.strip()) > 0]
                # any line with less than 3 words.
                qna = [qa for qa in qna if len(qa.split())>2]
                print(qna)
                qna_success = len(qna) % 2 == 0
                if not qna_success:
                    qna_resp = callGpt.get_turbo_call()(**call)
            qna = concat_array_two_at_a_time(qna)
            chunk_questions.append(qna)
        return chunk_questions
class LongSummarizer:
    def __init__(self, chunk_size=1000):
        self.chunk_size=1024
        self.name = "LongSummarizer"
        self.description = """
LongSummarizer:
    This tool takes a text document breaks it into chunks, then summarizes the chunks and creates chunk level and document level summary.

    Input params/args: 
        long_document (str): document to summarize.

    Returns: 
        str: summarized_document.

    Usage:
        `summarized_document = LongSummarizer()(text_document="Long document to summarize") # Note: this tool needs to be initialized first.`
    """
        self.info_dict = dict(title={"information_request": "Write a one line title describing the section.", 
                                     "information":"title"}, 
                             summary={"information_request": "Write a thorough and detailed summary for the current document fragment using the fragment text and `summary_till_now` as guide. Capture all details of this fragment.", 
                                      "information":"summary"},
                             summary_till_now={"information_request": "Write a coherent and detailed running summary using the provided 'summary till now' and the current fragment of document. Capture all details of what we have read till now including details of this part in 'summary_till_now'.", 
                                               "information":"summary till now"},
                             questions_and_answers={"information_request": "Generate multiple relevant questions and their answers which can be answered from this fragment with each question and answer in a different line. Don't do numbering of questions and answers", 
                                                    "information":"Generated Questions and Answers"})
        self.prompt = PromptTemplate(
            input_variables=["summary_till_now", "document", "information_request", "information"],
            template=""" 
Given below text is small part/fragment text of a larger document that we are reading sequentially.
"{document}"

Note: This is a raw unformatted document which may contain irrelevant text/syntax or other noise. Ignore what you consider noise or irrelevant.


You are also given a summary of what we have read till now (summary till now excluding this fragment text) from the larger document below:
{summary_till_now}


Based on the fragment of document and previous summary above provided you need to:
{information_request}


{information}:

""",
        )
    def __call__(self, long_document):
        
        chunks = ChunkText(long_document, self.chunk_size, 96)
        running_summary = "No summary yet, this is the first fragment."
        chunk_questions = []
        chunked_summary = []
        title = []
        
        for cnk in tqdm(chunks):
            rdict = dict()
            keys, prompts = [], []
            for k, v in self.info_dict.items():
                prompt = self.prompt.format(document=cnk, summary_till_now=running_summary, 
                                            information_request=v["information_request"], information=v["information"])
#                 print(prompt, "\n", "="*80)
                
                prompts.append(prompt)
                keys.append(k)
            calls = [{"text": p, "temperature": 0.7, "num_tokens": 512} for p in prompts]
            fns = [callGpt.get_turbo_call() if k=="summary_till_now" else call_ai21 for k in keys]
#             resp = call_api_parallel(calls, call_ai21)
            resp = call_api_parallel_multi_fn(calls, fns)
            resp = dict(zip(keys, resp))
            pprint(resp)
            chunked_summary.append(resp["summary"])
            qna_success = False
            qna_resp = resp["questions_and_answers"]
            while not qna_success:
                qna = [qa.strip() for qa in qna_resp.split("\n") if len(qa.strip()) > 0]
                # any line with less than 3 words.
                qna = [qa for qa in qna if len(qa.split())>2]
                qna_success = len(qna) % 2 == 0
                if not qna_success:
                    qna_call = calls[keys.index("questions_and_answers")]
                    qna_resp = call_ai21(**qna_call)
                    
            
            qna = concat_array_two_at_a_time(qna)
            chunk_questions.append(qna)
            running_summary = resp["summary_till_now"]
            title.append(resp["title"])
        full_length_summary = " ".join(chunked_summary)        
        return dict(full_length_summary=full_length_summary, title=title, chunked_summary=chunked_summary, chunks=chunks, running_summary=running_summary, chunk_questions=chunk_questions)

def create_document_index(pdf_url)->DocIndex:
    doc_text = PDFReaderTool()(pdf_url)
    full_summary = LongSummarizer()(doc_text)



    dpr = DeepReader()(doc_text, full_summary)
    dpr = {k: " ".join([d[k] for d in dpr]).strip() for k in list(dpr[0].keys())}


    qa_generations = QuestionAnswerGenerator()(doc_text, full_summary)


    full_summary["detailed_qna"] = qa_generations
    full_summary["deep_reader_details"] = dpr
    doc_index = DocIndex(pdf_url, 
                "pdf", 
                "scientific_article", doc_text, full_summary)
    return doc_index
