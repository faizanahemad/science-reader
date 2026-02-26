import os.path
import shutil
from datetime import datetime
from textwrap import dedent
from typing import Tuple, List

import semanticscholar.Paper
from filelock import FileLock, Timeout
from pathlib import Path
from prompts import math_formatting_instructions
from web_scraping import fetch_html
from transcribe_audio import transcribe_audio as transcribe_audio_file

try:
    import ujson as json
except ImportError:
    import json


from langchain_community.vectorstores.faiss import FAISS
from langchain_core.vectorstores import VectorStore
from common import *
from base import *

pd.options.display.float_format = "{:,.2f}".format
pd.set_option("max_colwidth", 800)
pd.set_option("display.max_columns", 100)

from loggers import getLoggers

logger, time_logger, error_logger, success_logger, log_memory_usage = getLoggers(
    __name__, logging.DEBUG, logging.INFO, logging.ERROR, logging.INFO
)
import time


class DocFAISS(FAISS):
    def merge_from(self, target: FAISS) -> None:
        """Merge another FAISS object with the current one.

        Add the target FAISS to the current one.

        Args:
            target: FAISS object you wish to merge into the current one

        Returns:
            None.
        """
        from langchain.docstore.base import AddableMixin
        from langchain.schema import Document

        if not isinstance(self.docstore, AddableMixin):
            raise ValueError("Cannot merge with this type of docstore")
        # Numerical index for target docs are incremental on existing ones
        starting_len = len(self.index_to_docstore_id)

        # Merge two IndexFlatL2
        self.index.merge_from(target.index)

        # Get id and docs from target FAISS object
        full_info = []
        existing_id = set(
            [target_id for i, target_id in self.index_to_docstore_id.items()]
        )
        for i, target_id in target.index_to_docstore_id.items():
            if target_id in existing_id:
                continue
            doc = target.docstore.search(target_id)
            if not isinstance(doc, Document):
                raise ValueError("Document should be returned")
            full_info.append((starting_len + i, target_id, doc))

        # Add information to docstore and index_to_docstore_id.
        self.docstore.add({_id: doc for _, _id, doc in full_info})
        index_to_id = {index: _id for index, _id, _ in full_info}
        self.index_to_docstore_id.update(index_to_id)


def create_index_faiss(chunks, embed_model, doc_id=None):
    from langchain.schema import Document

    if doc_id is None:
        doc_id = [""] * len(chunks)
    elif isinstance(doc_id, (str, int)):
        doc_id = [doc_id] * len(chunks)
    else:
        assert len(doc_id) == len(chunks) and isinstance(doc_id, (list, tuple))
        doc_id = [int(d) for d in doc_id]
    chunks = [
        Document(page_content=str(c), metadata={"order": i})
        for i, c in enumerate(chunks)
    ]
    for ix, chunk in enumerate(chunks):
        chunk.metadata["next"] = None if ix == len(chunks) - 1 else chunks[ix + 1]
        chunk.metadata["previous"] = None if ix == 0 else chunks[ix - 1]
        chunk.metadata["doc_id"] = doc_id[ix]
        chunk.metadata["index"] = ix
    db = DocFAISS.from_documents(chunks, embed_model)
    return db


# =============================================================================
# Multi-Facet Document Summarizer
# =============================================================================


class MultiFacetDocSummarizer:
    """
    A comprehensive document summarizer that generates multiple types of summaries/analyses.

    This class provides 6 different perspectives on a document:
    1. detailed - Long and detailed summary
    2. facts_stats - Facts, statistics and numbers in bullet points
    3. key_notes - Key notes, findings, and opinions
    4. complex_faq - Complex questions and their detailed answers
    5. nitpicks - Issues, shortcomings, and areas for improvement
    6. agentic_qa - Agentic Q&A session with one LLM asking, another answering

    All aspects are processed in parallel for efficiency.

    Usage:
        summarizer = MultiFacetDocSummarizer(api_keys, model_name="gpt-4", aspects=["detailed", "facts_stats"])
        for chunk in summarizer.summarize(document_text):
            print(chunk)
    """

    # Available aspects with their display titles
    ASPECT_TITLES = {
        "detailed": "📚 Detailed Summary",
        "facts_stats": "📊 Facts, Statistics & Numbers",
        "key_notes": "📝 Key Notes, Findings & Opinions",
        "complex_faq": "❓ Complex FAQ",
        "nitpicks": "🔎 Critical Analysis & Nitpicks",
        "agentic_qa": "🤖 Agentic Q&A Session",
        "topic_deep_dive": "🔬 Topic Deep Dive Analysis",
    }

    ALL_ASPECTS = list(ASPECT_TITLES.keys())

    def __init__(
        self,
        api_keys: dict,
        model_name: str = None,
        aspects: List[str] = None,
        chunk_size: int = 64000,
        chunk_overlap: int = 500,
    ):
        """
        Initialize the multi-facet document summarizer.

        Args:
            api_keys: Dictionary containing API keys for LLM services
            model_name: LLM model to use (default: CHEAP_LONG_CONTEXT_LLM[0])
            aspects: List of aspect IDs to generate (default: all 7 aspects)
                     Valid options: "detailed", "facts_stats", "key_notes",
                                   "complex_faq", "nitpicks", "agentic_qa", "topic_deep_dive"
            chunk_size: Maximum tokens per chunk for processing (default: 64000)
            chunk_overlap: Token overlap between chunks (default: 500)
        """
        self.api_keys = api_keys
        self.model_name = model_name or CHEAP_LONG_CONTEXT_LLM[0]
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        # Validate and set aspects
        if aspects is None:
            self.aspects = self.ALL_ASPECTS.copy()
        else:
            invalid = set(aspects) - set(self.ALL_ASPECTS)
            if invalid:
                raise ValueError(
                    f"Invalid aspects: {invalid}. Valid options: {self.ALL_ASPECTS}"
                )
            self.aspects = aspects

        # Map aspect IDs to their generator methods
        self._aspect_methods = {
            "detailed": self._generate_detailed,
            "facts_stats": self._generate_facts_stats,
            "key_notes": self._generate_key_notes,
            "complex_faq": self._generate_complex_faq,
            "nitpicks": self._generate_nitpicks,
            "agentic_qa": self._generate_agentic_qa,
            "topic_deep_dive": self._generate_topic_deep_dive,
        }

    def _get_splitter(self, chunk_size: int = None, chunk_overlap: int = None):
        """Get a configured text splitter instance."""
        from text_splitter import RecursiveChunkTextSplitter

        return RecursiveChunkTextSplitter(
            chunk_size=chunk_size or self.chunk_size,
            chunk_overlap=chunk_overlap or self.chunk_overlap,
        )

    def _get_llm(self, model_name: str = None):
        """Get a configured LLM instance."""
        return CallLLm(self.api_keys, model_name=model_name or self.model_name)

    def _process_chunks_parallel(
        self, chunks: List[str], prompt_template: str, temperature: float = 0.5
    ) -> List[str]:
        """
        Process multiple chunks in parallel using the LLM.

        Args:
            chunks: List of text chunks to process
            prompt_template: Prompt template with {text} placeholder
            temperature: LLM temperature setting

        Returns:
            List of LLM responses for each chunk
        """
        llm = self._get_llm()

        if len(chunks) == 1:
            return [
                llm(
                    prompt_template.format(text=chunks[0]),
                    temperature=temperature,
                    stream=False,
                )
            ]

        futures = []
        for chunk in chunks:
            prompt = prompt_template.format(text=chunk)
            future = get_async_future(
                llm, prompt, temperature=temperature, stream=False
            )
            futures.append(future)

        return [sleep_and_get_future_result(f) for f in futures]

    def _generate_detailed(self, text: str) -> str:
        """Generate a long and detailed summary of the document."""
        splitter = self._get_splitter()
        chunks = splitter(text)

        prompt_template = dedent("""
        You are an expert document analyst. Write a long, detailed, and comprehensive summary of the following document section.
        
        Your summary should:
        - Cover all major topics, arguments, and conclusions
        - Preserve important details and nuances
        - Maintain logical flow and structure
        - Include relevant context and background information
        - Be thorough yet readable
        
        {math_instructions}
        
        Document section:
        ```
        {{text}}
        ```
        
        Write a detailed and comprehensive summary:
        """).format(math_instructions="")

        chunk_summaries = self._process_chunks_parallel(
            chunks, prompt_template, temperature=0.5
        )

        if len(chunk_summaries) == 1:
            return chunk_summaries[0]

        # Combine chunk summaries
        combine_prompt = dedent("""
        You are an expert document analyst. Combine the following section summaries into one cohesive, 
        comprehensive, and detailed summary. Ensure smooth transitions, remove redundancy, and maintain 
        all important information.
        
        {math_instructions}
        
        Section summaries:
        {summaries}
        
        Write the combined comprehensive summary:
        """).format(math_instructions="", summaries="\n\n---\n\n".join(chunk_summaries))

        llm = self._get_llm()
        return llm(combine_prompt, temperature=0.4, stream=False)

    def _generate_facts_stats(self, text: str) -> str:
        """Extract facts, statistics, and numbers in bullet point format."""
        splitter = self._get_splitter()
        chunks = splitter(text)

        prompt_template = dedent("""
        You are a meticulous data analyst. Extract ALL facts, statistics, numbers, metrics, and quantitative data from the following text.
        
        Format your response as concise bullet points. For each item include:
        - The specific number, statistic, or fact
        - Brief context (what it refers to)
        - Source/location in document if mentioned
        
        Categories to look for:
        • Percentages and ratios
        • Dates and time periods
        • Financial figures (revenue, costs, etc.)
        • Performance metrics
        • Population/sample sizes
        • Measurements and quantities
        • Rankings and comparisons
        • Key factual claims
        
        Document section:
        ```
        {text}
        ```
        
        Extract all facts, stats, and numbers in bullet point format:
        """)

        chunk_results = self._process_chunks_parallel(
            chunks, prompt_template, temperature=0.3
        )

        if len(chunk_results) == 1:
            return chunk_results[0]

        # Consolidate
        combine_prompt = dedent("""
        Consolidate the following extracted facts, statistics, and numbers. 
        Remove duplicates, organize by category, and ensure concise bullet point format.
        
        Extracted data:
        {data}
        
        Provide the consolidated, deduplicated list organized by category:
        """).format(data="\n\n".join(chunk_results))

        llm = self._get_llm(CHEAP_LLM[0])
        return llm(combine_prompt, temperature=0.2, stream=False)

    def _generate_key_notes(self, text: str) -> str:
        """Extract key notes, findings, and opinions in concise format."""
        splitter = self._get_splitter()
        chunks = splitter(text)

        prompt_template = dedent("""
        You are an expert analyst. Extract all KEY notes, findings, and opinions from the following text.
        
        Organize your extraction into three sections:
        
        ## Key Notes
        - Important observations and points to remember
        - Critical information that readers should note
        
        ## Findings
        - Research results and discoveries
        - Conclusions drawn from evidence
        - Outcomes and results mentioned
        
        ## Opinions & Assessments
        - Author's viewpoints and judgments
        - Recommendations and suggestions
        - Evaluative statements and critiques
        
        Be concise but capture the essence of each point.
        
        Document section:
        ```
        {text}
        ```
        
        Extract key notes, findings, and opinions:
        """)

        chunk_results = self._process_chunks_parallel(
            chunks, prompt_template, temperature=0.4
        )

        if len(chunk_results) == 1:
            return chunk_results[0]

        # Consolidate
        combine_prompt = dedent("""
        Consolidate the following key notes, findings, and opinions from different sections of a document.
        Organize into three clear sections (Key Notes, Findings, Opinions & Assessments).
        Remove redundancy while preserving all unique insights.
        
        Extracted content:
        {content}
        
        Provide the consolidated key notes, findings, and opinions:
        """).format(content="\n\n---\n\n".join(chunk_results))

        llm = self._get_llm(CHEAP_LLM[0])
        return llm(combine_prompt, temperature=0.3, stream=False)

    def _generate_complex_faq(self, text: str) -> str:
        """Generate complex questions and detailed answers as FAQ document."""
        splitter = self._get_splitter()
        chunks = splitter(text)

        prompt_template = dedent("""
        You are an expert educator creating challenging exam questions. Based on the following text, 
        generate complex, thought-provoking questions and their detailed answers.
        
        Types of questions to create:
        1. **Analytical Questions**: Questions requiring analysis of relationships, causes, and effects
        2. **Synthesis Questions**: Questions requiring combining ideas from different parts
        3. **Evaluation Questions**: Questions requiring critical judgment and assessment
        4. **Application Questions**: Questions about applying concepts to new situations
        5. **Edge Case Questions**: Questions about limitations, exceptions, and boundary conditions
        
        For each question:
        - Make it genuinely challenging (not simple recall)
        - Provide a comprehensive, well-reasoned answer
        - Reference specific parts of the text when relevant
        
        {math_instructions}
        
        Document section:
        ```
        {{text}}
        ```
        
        Generate 5-7 complex FAQ entries in this format:
        
        ### Q1: [Complex Question]
        **Answer:** [Detailed answer]
        
        ### Q2: [Complex Question]
        **Answer:** [Detailed answer]
        
        (continue for all questions)
        """).format(math_instructions="")

        chunk_faqs = self._process_chunks_parallel(
            chunks, prompt_template, temperature=0.6
        )

        if len(chunk_faqs) == 1:
            return chunk_faqs[0]

        # Combine and curate
        combine_prompt = dedent("""
        You have multiple sets of complex FAQ entries from different sections of a document.
        Combine them into one cohesive FAQ document:
        
        1. Remove duplicate or highly similar questions
        2. Keep the most challenging and insightful questions
        3. Ensure answers are comprehensive and accurate
        4. Organize questions from foundational to advanced
        5. Aim for 10-15 high-quality FAQ entries total
        
        {math_instructions}
        
        FAQ entries to consolidate:
        {faqs}
        
        Provide the consolidated Complex FAQ document:
        """).format(math_instructions="", faqs="\n\n---\n\n".join(chunk_faqs))

        llm = self._get_llm()
        return llm(combine_prompt, temperature=0.5, stream=False)

    def _generate_nitpicks(self, text: str) -> str:
        """Identify issues, shortcomings, and areas for improvement."""
        splitter = self._get_splitter()
        chunks = splitter(text)

        prompt_template = dedent("""
        You are a critical reviewer and editor. Analyze the following text for issues, shortcomings, and areas of improvement.
        
        Look for:
        
        ## Logical Issues
        - Logical fallacies or weak arguments
        - Unsupported claims
        - Contradictions or inconsistencies
        
        ## Missing Information
        - Important topics not covered
        - Unexplained concepts or terms
        - Missing context or background
        
        ## Clarity Issues
        - Ambiguous statements
        - Confusing explanations
        - Poor organization
        
        ## Methodological Concerns (if applicable)
        - Sample size issues
        - Selection bias
        - Confounding variables
        - Validity concerns
        
        ## Minor Nitpicks
        - Small errors or typos noticed
        - Formatting issues
        - Citation/reference problems
        
        Be specific and constructive in your critique.
        
        Document section:
        ```
        {text}
        ```
        
        Provide your critical analysis:
        """)

        chunk_critiques = self._process_chunks_parallel(
            chunks, prompt_template, temperature=0.5
        )

        if len(chunk_critiques) == 1:
            return chunk_critiques[0]

        # Consolidate
        combine_prompt = dedent("""
        Consolidate the following critical analyses from different sections of a document.
        
        Instructions:
        1. Group issues by category (Logical, Missing Info, Clarity, Methodological, Nitpicks)
        2. Remove duplicate concerns
        3. Prioritize by severity (major issues first)
        4. Be constructive - note both issues and potential solutions
        
        Critical analyses:
        {critiques}
        
        Provide the consolidated critical analysis:
        """).format(critiques="\n\n---\n\n".join(chunk_critiques))

        llm = self._get_llm(CHEAP_LLM[0])
        return llm(combine_prompt, temperature=0.4, stream=False)

    def _generate_agentic_qa(self, text: str) -> str:
        """
        Generate agentic Q&A with one LLM asking questions, another answering.

        This method is fully parallelized:
        1. Question generation runs in parallel across all chunks
        2. Answer generation runs in parallel for each chunk's questions
        """
        splitter = self._get_splitter()
        chunks = splitter(text)

        # Limit chunks to process (first 8 for questions, use all for context)
        question_chunks = chunks[:8]
        full_text = "\n\n".join(chunks)[:100000]  # Limit context size

        # Question generation prompt
        question_prompt = dedent("""
        You are a brilliant, curious intellectual who has just read a fascinating document. 
        Generate stimulating, thought-provoking questions that:
        
        1. **Challenge assumptions** - Question the underlying premises
        2. **Seek deeper understanding** - Ask "why" and "how" questions
        3. **Explore implications** - What does this mean for the future?
        4. **Connect to broader context** - How does this relate to other fields/ideas?
        5. **Probe edge cases** - What about unusual situations?
        6. **Question methodology** - How do we know this is true?
        7. **Seek practical applications** - How can this be used?
        
        Be genuinely curious and intellectually rigorous. Avoid simple factual questions.
        
        Document:
        ```
        {text}
        ```
        
        Generate 5-8 stimulating questions (just the questions, numbered):
        """)

        # =====================================================================
        # PHASE 1: Generate questions in parallel for all chunks
        # =====================================================================
        question_futures = []
        for chunk in question_chunks:
            llm_questioner = self._get_llm(CHEAP_LLM[0])
            prompt = question_prompt.format(text=chunk)
            future = get_async_future(
                llm_questioner, prompt, temperature=0.7, stream=False
            )
            question_futures.append(future)

        # Wait for all question generation to complete
        all_questions = [sleep_and_get_future_result(f) for f in question_futures]

        # =====================================================================
        # PHASE 2: Answer each chunk's questions in parallel
        # =====================================================================
        answer_prompt_template = dedent("""
        You are a knowledgeable expert who has deeply studied the following document. 
        Answer the questions below with insight, nuance, and intellectual rigor.
        
        For each answer:
        - Be concise but substantive (2-4 paragraphs per answer)
        - Reference specific parts of the document when relevant
        - Acknowledge uncertainty or limitations where appropriate
        - Provide your own thoughtful analysis, not just summary
        
        {math_instructions}
        
        Document:
        ```
        {text}
        ```
        
        Questions to answer:
        {questions}
        
        Provide your answers in this format:
        
        ---
        
        **🎯 Q:** [Question]
        
        **💡 Answer:** [Your insightful answer]
        
        ---
        
        (continue for all questions)
        """).format(math_instructions="", text=full_text, questions="{questions}")

        # Launch answer generation in parallel for each question batch
        answer_futures = []
        for questions in all_questions:
            if questions.strip():  # Only process non-empty question batches
                llm_answerer = self._get_llm()
                prompt = answer_prompt_template.format(questions=questions)
                future = get_async_future(
                    llm_answerer, prompt, temperature=0.6, stream=False
                )
                answer_futures.append(future)

        # Wait for all answer generation to complete
        all_answers = [sleep_and_get_future_result(f) for f in answer_futures]

        # =====================================================================
        # Combine all Q&A sessions
        # =====================================================================
        header = dedent("""
        # 🔍 Agentic Q&A Session
        
        *An intellectual dialogue exploring the document through probing questions and expert answers.*
        
        """)

        # Combine all answers with section dividers
        combined_dialogue = "\n\n".join(all_answers)

        return header + combined_dialogue

    def _generate_topic_deep_dive(self, text: str) -> str:
        """
        Generate a deep dive analysis organized by topics and sections.

        This is a 2-step parallel process:
        1. Extract topics from up to 8 chunks in parallel (no consolidation LLM call)
        2. For each unique topic, run a single comprehensive LLM call to get
           summary, facts, takeaways, analysis, detailed notes, and implications

        Args:
            text: The document text to analyze

        Returns:
            Comprehensive topic-by-topic analysis
        """
        splitter = self._get_splitter()
        chunks = splitter(text)
        full_text = self._get_splitter(chunk_size=500_000, chunk_overlap=1_000)(text)[
            :1
        ]
        full_text = "\n\n".join(full_text)

        # =====================================================================
        # PHASE 1: Extract topics from chunks (parallel, no consolidation LLM)
        # =====================================================================
        topic_extraction_prompt = dedent("""
        You are an expert document analyst. Analyze the following document section and identify 
        the main topics, sections, and themes covered.
        
        For each topic/section you identify, provide:
        1. **Topic Name**: A clear, descriptive name
        2. **Keywords**: 3-5 key terms associated with this topic
        3. **Brief Description**: 1-2 sentences describing what this topic covers
        
        Focus on substantive topics that would benefit from deeper analysis.
        Aim for 2-4 distinct topics from this section.
        
        Document section:
        ```
        {text}
        ```
        
        List the topics in this exact format (use --- as separator between topics):
        
        ### Topic: [Topic Name]
        **Keywords:** keyword1, keyword2, keyword3
        **Description:** Brief description of the topic
        
        ---
        
        (repeat for each topic, separated by ---)
        """)

        # Extract topics from chunks in parallel (up to 8 chunks)
        topic_futures = []
        for chunk in chunks[:8]:
            llm = self._get_llm(CHEAP_LLM[0])
            prompt = topic_extraction_prompt.format(text=chunk)
            future = get_async_future(llm, prompt, temperature=0.5, stream=False)
            topic_futures.append(future)

        # Wait for topic extraction
        chunk_topics = [sleep_and_get_future_result(f) for f in topic_futures]

        # Parse and deduplicate topics locally (no LLM consolidation)
        all_topics = {}  # Use dict to deduplicate by normalized topic name

        for chunk_result in chunk_topics:
            topic_blocks = [
                t.strip()
                for t in chunk_result.split("---")
                if t.strip() and "Topic:" in t
            ]

            for topic_block in topic_blocks:
                topic_name = "Unknown Topic"
                keywords = ""
                description = ""

                if "Topic:" in topic_block:
                    try:
                        topic_name = (
                            topic_block.split("Topic:")[1]
                            .split("\n")[0]
                            .strip()
                            .strip("#")
                            .strip()
                        )
                    except:
                        pass

                if "Keywords:" in topic_block:
                    try:
                        keywords = (
                            topic_block.split("Keywords:")[1]
                            .split("\n")[0]
                            .strip()
                            .strip("*")
                            .strip()
                        )
                    except:
                        pass

                if "Description:" in topic_block:
                    try:
                        description = (
                            topic_block.split("Description:")[1]
                            .split("\n")[0]
                            .strip()
                            .strip("*")
                            .strip()
                        )
                    except:
                        pass

                # Normalize topic name for deduplication (lowercase, strip)
                normalized_name = topic_name.lower().strip()

                if normalized_name and normalized_name != "unknown topic":
                    if normalized_name not in all_topics:
                        all_topics[normalized_name] = {
                            "name": topic_name,
                            "keywords": set(
                                k.strip() for k in keywords.split(",") if k.strip()
                            ),
                            "description": description,
                        }
                    else:
                        # Merge keywords from duplicate topics
                        all_topics[normalized_name]["keywords"].update(
                            k.strip() for k in keywords.split(",") if k.strip()
                        )
                        # Keep longer description
                        if len(description) > len(
                            all_topics[normalized_name]["description"]
                        ):
                            all_topics[normalized_name]["description"] = description

        # Convert to list and limit to 8 topics
        unique_topics = [
            {
                "name": data["name"],
                "keywords": ", ".join(list(data["keywords"])[:6]),
                "description": data["description"],
            }
            for data in list(all_topics.values())[:8]
        ]

        # =====================================================================
        # PHASE 2: Single comprehensive LLM call per topic (parallel)
        # =====================================================================
        comprehensive_prompt = dedent("""
        You are an expert document analyst. Provide a comprehensive deep-dive analysis of the topic 
        "{topic}" as covered in the document below.
        
        **Topic:** {topic}
        **Keywords to focus on:** {keywords}
        **Topic Description:** {description}
        
        {math_instructions}
        
        Document:
        ```
        {text}
        ```
        
        Provide your analysis in the following structured format:
        
        ### 📝 Summary
        A detailed summary of this topic (3-5 paragraphs covering main concepts, how the topic is developed, key arguments).
        
        ### 📊 Facts & Data
        All facts, statistics, numbers, dates, named entities, and concrete data related to this topic (bullet points).
        
        ### 💡 Key Takeaways
        The most important insights, conclusions, and actionable points from this topic (bullet points).
        
        ### 🔍 Critical Analysis
        Critical evaluation including strengths, weaknesses, assumptions, evidence quality, biases, and unanswered questions.
        
        ### 📋 Detailed Notes
        Comprehensive notes covering technical details, methodologies, definitions, and explanations.
        
        ### 🔗 Implications & Connections
        Broader implications, connections to other fields, practical applications, future directions, and how this relates to other topics.
        
        Write your comprehensive analysis below:
        """)

        # Launch parallel analysis for each topic
        topic_futures = []
        for topic in unique_topics:
            llm = self._get_llm()
            prompt = comprehensive_prompt.format(
                topic=topic["name"],
                keywords=topic["keywords"],
                description=topic["description"],
                text=full_text,
                math_instructions="",
            )
            future = get_async_future(llm, prompt, temperature=0.5, stream=False)
            topic_futures.append(
                {"name": topic["name"], "keywords": topic["keywords"], "future": future}
            )

        # =====================================================================
        # Collect results and format output
        # =====================================================================
        header = dedent("""
        # 🔬 Topic Deep Dive Analysis
        
        *A comprehensive exploration of key topics and themes in the document.*
        
        """)

        # Add table of contents
        toc = "\n## 📑 Topics Covered\n\n"
        for i, topic in enumerate(unique_topics, 1):
            toc += f"{i}. **{topic['name']}** - {topic['keywords']}\n"
        toc += "\n---\n"

        result_sections = [header, toc]

        for topic_data in topic_futures:
            topic_name = topic_data["name"]
            keywords = topic_data["keywords"]
            future = topic_data["future"]

            # Topic header
            topic_header = f"\n\n## 📌 {topic_name}\n\n"
            topic_header += f"**Keywords:** {keywords}\n\n"
            result_sections.append(topic_header)

            try:
                result = sleep_and_get_future_result(future)
                result_sections.append(result)
            except Exception as e:
                result_sections.append(
                    f"*Error generating analysis for this topic: {str(e)}*\n"
                )

            result_sections.append("\n\n---\n")

        return "".join(result_sections)

    def summarize(self, text: str):
        """
        Generate multi-facet summary of the document.

        This is the main entry point. It launches all selected aspects in parallel
        and yields results as they complete.

        Args:
            text: The document text to summarize

        Yields:
            Formatted strings for each section of the summary
        """
        # Yield header
        header = dedent("""
        # 📖 Multi-Facet Document Summary
        
        *A comprehensive analysis of the document from multiple perspectives.*
        
        ---
        
        """)
        yield header

        # Launch all aspects in parallel
        futures = {}
        for aspect_id in self.aspects:
            method = self._aspect_methods[aspect_id]
            future = get_async_future(method, text)
            futures[aspect_id] = future

        # Yield results in order
        for aspect_id in self.aspects:
            title = self.ASPECT_TITLES[aspect_id]
            future = futures[aspect_id]

            # Section header
            section_header = f"\n\n## {title}\n\n"
            yield section_header

            try:
                result = sleep_and_get_future_result(future)
                yield result
            except Exception as e:
                error_msg = f"*Error generating this section: {str(e)}*\n"
                yield error_msg
                logger.error(f"Error in {aspect_id}: {e}")

            # Section separator
            yield "\n\n---\n"

    def summarize_sync(self, text: str) -> str:
        """
        Generate multi-facet summary synchronously (non-streaming).

        Args:
            text: The document text to summarize

        Returns:
            Complete summary as a single string
        """
        return "".join(self.summarize(text))


class DocIndex:
    def __init__(
        self,
        doc_source,
        doc_filetype,
        doc_type,
        doc_text,
        chunk_size,
        full_summary,
        openai_embed,
        storage,
        keys,
    ):
        init_start = time.time()
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))
        raw_data = dict(chunks=full_summary["chunks"])
        raw_index_future = get_async_future(
            create_index_faiss,
            raw_data["chunks"],
            openai_embed,
            doc_id=self.doc_id,
        )
        raw_data_small = dict(chunks=full_summary["chunks_small"])
        raw_index_small_future = get_async_future(
            create_index_faiss,
            raw_data_small["chunks"],
            openai_embed,
            doc_id=self.doc_id,
        )

        self._visible = False
        self._chunk_size = chunk_size
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        # if parent folder of doc_source is not same as storage, then copy the doc_source to storage
        if self.is_local and os.path.dirname(
            os.path.expanduser(doc_source)
        ) != os.path.expanduser(storage):
            # shutil.copy(doc_source, storage) # move not copy
            try:
                shutil.move(doc_source, storage)
                # Handle shutil.Error where file already exists
            except shutil.Error as e:
                # Replace the file in storage with the new one
                shutil.copy(doc_source, storage)
                doc_source = os.path.join(storage, os.path.basename(doc_source))

            doc_source = os.path.join(storage, os.path.basename(doc_source))
            self.doc_source = doc_source
        self.doc_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type
        self._title = ""
        self._short_summary = ""
        self._display_name = None
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = [
            "indices",
            "raw_data",
            "review_data",
            "static_data",
            "_paper_details",
        ]
        print(doc_filetype)
        assert doc_filetype in [
            "pdf",
            "html",
            "word",
            "jpeg",
            "md",
            "jpg",
            "png",
            "csv",
            "xls",
            "xlsx",
            "jpeg",
            "bmp",
            "svg",
            "parquet",
        ] and ("http" in doc_source or os.path.exists(doc_source))

        if (
            hasattr(self, "is_local")
            and self.is_local
            or "arxiv.org" not in self.doc_source
        ):

            def set_title_summary():
                chunks = "\n\n".join(raw_data["chunks"][0:8])
                short_summary = CallLLm(
                    keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False
                )(
                    f"""Provide a summary for the below text: \n'''{chunks}''' \nSummary: \n""",
                )
                title = CallLLm(
                    keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False, use_16k=True
                )(
                    f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n"""
                )
                setattr(self, "_title", title)
                setattr(self, "_short_summary", short_summary)

            set_title_summary_future = get_async_future(set_title_summary)
        else:
            set_title_summary_future = wrap_in_future(None)
        static_data = dict(
            doc_source=doc_source,
            doc_filetype=doc_filetype,
            doc_type=doc_type,
            doc_text=doc_text,
        )
        del full_summary["chunks"]
        _paper_details = None
        # self.set_doc_data("static_data", None, static_data)
        # self.set_doc_data("raw_data", None, raw_data)

        futures = [
            get_async_future(self.set_doc_data, "static_data", None, static_data),
            get_async_future(self.set_doc_data, "raw_data", None, raw_data),
        ]
        indices = dict(
            summary_index=create_index_faiss(
                ["EMPTY"],
                openai_embed,
            )
        )
        futures.append(get_async_future(self.set_doc_data, "indices", None, indices))
        for f in futures:
            sleep_and_get_future_result(f, 0.1)
        time_logger.info(
            f"DocIndex init time without raw index: {(time.time() - init_start):.2f}"
        )
        self.set_api_keys(keys)
        self.long_summary_waiting = time.time()

        def set_raw_index_small():
            _ = sleep_and_get_future_result(set_title_summary_future)
            brief_summary = self.title + "\n" + self.short_summary
            brief_summary = (
                ("Summary:\n" + brief_summary + "\n\n")
                if len(brief_summary.strip()) > 0
                else ""
            )
            self._brief_summary = brief_summary

            text = self.brief_summary + doc_text
            self._text_len = get_gpt4_word_count(text)
            self._brief_summary_len = get_gpt3_word_count(brief_summary)
            self._raw_index = sleep_and_get_future_result(raw_index_future)
            self._raw_index_small = sleep_and_get_future_result(raw_index_small_future)

            def get_summary(stream):
                return "".join(convert_stream_to_iterable(stream))

            f1 = get_async_future(get_summary, self.get_doc_long_summary())
            f2 = get_async_future(get_summary, self.get_doc_long_summary_v2())
            while not f1.done() or not f2.done():
                time.sleep(1)
            # self._long_summary = "".join(f1.result()) + "".join(f2.result())
            time_logger.info(
                f"DocIndex init time with raw index and title, summary: {(time.time() - init_start):.2f}"
            )

        set_raw_index_small()

    @property
    def brief_summary_len(self):
        if hasattr(self, "_brief_summary_len"):
            return self._brief_summary_len
        else:
            return get_gpt3_word_count(self.brief_summary)

    @property
    def raw_index(self):
        if hasattr(self, "_raw_index"):
            return self._raw_index
        else:
            return None

    @property
    def raw_index_small(self):
        if hasattr(self, "_raw_index_small"):
            return self._raw_index_small
        else:
            return None

    @property
    def text_len(self):
        return self._text_len

    @property
    def brief_summary(self):
        return self._brief_summary

    @property
    def chunk_size(self):
        if hasattr(self, "_chunk_size"):
            return self._chunk_size
        else:
            return LARGE_CHUNK_LEN

    @property
    def visible(self):
        return self._visible if hasattr(self, "_visible") else True

    def get_doc_data(
        self,
        top_key,
        inner_key=None,
    ):
        import dill

        doc_id = self.doc_id

        folder = self._storage
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")

        try:
            assert top_key in self.store_separate
        except Exception as e:
            raise ValueError(f"Invalid top_key {top_key} provided")
        logger.debug(
            f"Get doc data for top_key = {top_key}, inner_key = {inner_key}, folder = {folder}, filepath = {filepath} exists = {os.path.exists(filepath)}, json filepath = {json_filepath} exists = {os.path.exists(json_filepath)}, already loaded = {getattr(self, top_key, None) is not None}"
        )
        if getattr(self, top_key, None) is not None:
            if inner_key is not None:
                return getattr(self, top_key, None).get(inner_key, None)
            else:
                return getattr(self, top_key, None)
        else:
            if os.path.exists(json_filepath):
                with open(json_filepath, "r") as f:
                    obj = json.load(f)
                setattr(self, top_key, obj)
                if inner_key is not None:
                    return obj.get(inner_key, None)
                else:
                    return obj
            elif os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    obj = dill.load(f)
                if top_key not in ["indices", "_paper_details"]:
                    with open(json_filepath, "w") as f:
                        json.dump(obj, f)
                setattr(self, top_key, obj)
                if inner_key is not None:
                    return obj.get(inner_key, None)
                else:
                    return obj
            else:
                return None

    def set_doc_data(self, top_key, inner_key, value, overwrite=False):
        import dill

        doc_id = self.doc_id
        folder = self._storage
        print(folder)
        filepath = os.path.join(folder, f"{doc_id}-{top_key}.partial")
        json_filepath = os.path.join(folder, f"{doc_id}-{top_key}.json")
        path = Path(folder)
        lock_location = os.path.join(
            os.path.join(path.parent.parent, "locks"), f"{doc_id}-{top_key}"
        )
        lock = FileLock(f"{lock_location}.lock")
        with lock.acquire(timeout=600):
            if inner_key is not None:
                tk = self.get_doc_data(top_key)
                if tk is None:
                    setattr(self, top_key, dict())

                inner = self.get_doc_data(top_key, inner_key)
                assert (
                    type(inner) == type(value)
                    or inner is None
                    or (
                        isinstance(inner, (tuple, list))
                        and isinstance(value, (tuple, list))
                    )
                )
                if isinstance(inner, dict) and not overwrite:
                    inner.update(value)
                elif isinstance(inner, list) and not overwrite:
                    inner.extend(value)
                elif isinstance(inner, str) and not overwrite:
                    inner = inner + value
                elif isinstance(inner, tuple) and not overwrite:
                    inner = inner + value
                else:
                    inner = value
                getattr(self, top_key, None)[inner_key] = inner
            else:
                tk = self.get_doc_data(top_key, None)
                if top_key == "review_data" and isinstance(tk, dict):
                    tk = list(tk.values())
                assert (type(tk) == type(value) or tk is None or value is None) or (
                    isinstance(tk, (tuple, list)) and isinstance(value, (tuple, list))
                )
                if tk is not None and type(tk) == type(value):
                    if isinstance(tk, dict) and not overwrite:
                        tk.update(value)
                    elif isinstance(tk, list) and not overwrite:
                        tk.extend(value)
                    elif isinstance(tk, str) and not overwrite:
                        tk = tk + value
                    elif isinstance(tk, tuple) and not overwrite:
                        tk = tk + value
                    else:
                        tk = value
                    setattr(self, top_key, tk)
                elif tk is None and value is not None:
                    setattr(self, top_key, value)
                else:
                    setattr(self, top_key, None)
            if top_key not in ["indices", "_paper_details"]:
                with open(json_filepath, "w") as f:
                    json.dump(getattr(self, top_key, None), f)
            else:
                with open(os.path.join(filepath), "wb") as f:
                    dill.dump(getattr(self, top_key, None), f)

    def get_short_answer(
        self, query, mode=defaultdict(lambda: False), save_answer=True
    ):
        answer = ""
        for ans in self.streaming_get_short_answer(query, mode, save_answer):
            answer += ans
        return answer

    def set_model_overrides(self, overrides: dict) -> None:
        """
        Store per-document model overrides.

        Parameters
        ----------
        overrides : dict
            Mapping of override keys to model names.
        """
        if isinstance(overrides, dict):
            self._model_overrides = overrides
        else:
            self._model_overrides = {}

    def get_model_override(self, key: str, default: str | None = None) -> str | None:
        """
        Resolve a model override for this document.

        Parameters
        ----------
        key : str
            Override key.
        default : str | None, optional
            Default model name.

        Returns
        -------
        str | None
            Model name or default.
        """
        overrides = getattr(self, "_model_overrides", None)
        if not isinstance(overrides, dict):
            return default
        value = overrides.get(key)
        return value or default

    def get_raw_doc_text(self):
        return (
            self.brief_summary + "\n\n" + self.get_doc_data("static_data", "doc_text")
        )

    def get_doc_long_summary(self):
        # while hasattr(self, "long_summary_waiting") and time.time() - self.long_summary_waiting < 90 and not hasattr(self, "_long_summary"):
        #     time.sleep(0.1)
        text = (
            self.brief_summary
            + "\n---\n"
            + self.get_doc_data("static_data", "doc_text")
        )
        summary_model = self.get_model_override(
            "doc_long_summary_model", CHEAP_LONG_CONTEXT_LLM[0]
        )
        llm = CallLLm(self.get_api_keys(), model_name=summary_model)
        long_summary = ""
        if hasattr(self, "_long_summary"):
            yield self._long_summary
            return

        elif (
            "arxiv" in self.doc_source
            or "aclanthology" in self.doc_source
            or "aclweb" in self.doc_source
        ):
            paper_summary = prompts.paper_summary_prompt
            llm_context = (
                paper_summary
                + "\n\n<context>\n"
                + text
                + "\n</context>\nWrite a detailed and comprehensive summary of the paper below.\n\n"
            )
            paper_model = self.get_model_override(
                "doc_long_summary_model", EXPENSIVE_LLM[0]
            )
            llm = CallLLm(self.get_api_keys(), model_name=paper_model)
            document_type = "scientific paper"

        else:
            llm = CallLLm(self.get_api_keys(), model_name=summary_model)

            # Step 1: Identify document type and key aspects
            identify_prompt = dedent("""
            Analyze the following document and:
            1. Identify the type of document (e.g., research paper, technical report, business proposal, etc.) from the list of allowed document types.
            2. List the key aspects and key takeaways that should be included in a highly detailed and comprehensive summary for this type of document.

            Allowed document types:
            ```
            ["scientific paper", "business report", "business proposal", "business plan", "technical documentation", "api documentation", "user manual", "other"]
            ```

            Scientific Papers can include research papers, technical papers, arxiv papers, aclanthology papers, aclweb papers as well.
            For scientific paper document type, just leave detailed_summary_prompt blank. We already have a detailed summary prompt for scientific papers.


            Respond in the following xml like format:

            ```xml
            <response>

            <document_type>
            [Your identified document type]
            </document_type>

            <key_aspects>
            [List of key aspects for understanding the document]
            </key_aspects>

            <key_takeaways>
            [Detailed list of key takeaways in bullet points]
            </key_takeaways>

            <key_numbers>
            [Detailed list of key numbers or values or metrics or statistics or data points or results in bullet points]
            </key_numbers>


            </response>
            ```

            Document text:

            ```
            {text}
            ```


            Your response should be in the xml format given above. Write the response below.
            """)

            identification = llm(
                identify_prompt.format(text=text[:64_000]),
                temperature=0.7,
                stream=False,
            )
            document_type = (
                identification.split("<document_type>")[1]
                .split("</document_type>")[0]
                .lower()
                .strip()
            )
            key_aspects = (
                identification.split("<key_aspects>")[1]
                .split("</key_aspects>")[0]
                .lower()
                .strip()
            )
            key_takeaways = (
                identification.split("<key_takeaways>")[1]
                .split("</key_takeaways>")[0]
                .lower()
                .strip()
            )
            key_numbers = (
                identification.split("<key_numbers>")[1]
                .split("</key_numbers>")[0]
                .lower()
                .strip()
            )

            long_summary += f"\n\n<b> Document Type: {document_type} </b> \n </br>"
            yield f"\n\n<b> Document Type: {document_type} </b> \n </br>"

            long_summary += f"\n\n<b> Key Takeaways:</b> \n{key_takeaways} \n \n </br>"
            yield f"\n\n<b> Key Takeaways:</b> \n{key_takeaways} \n \n </br>"

            long_summary += f"\n\n<b> Key Numbers:</b> \n{key_numbers} \n \n </br>"
            yield f"\n\n<b> Key Numbers:</b> \n{key_numbers} \n \n </br>"

            if document_type == "scientific paper" or document_type == "research paper":
                detailed_summary_prompt = prompts.paper_summary_prompt
            else:
                detailed_summary_prompt = ""
            logger.info(f"Document Type: {document_type}, ")
            if document_type not in [
                "scientific paper",
                "technical report",
                "research paper",
                "technical paper",
                "business report",
                "business proposal",
                "business plan",
                "technical documentation",
                "api documentation",
                "user manual",
                "other",
            ]:
                raise ValueError(
                    f"Invalid document type {document_type} identified. Please try again."
                )

            # Step 2: Generate the comprehensive summary
            summary_prompt = dedent(f"""
            We have read the document and following is the analysis of the document:

            Document Type: {{document_type}}

            Key Aspects: 
            {{key_aspects}}

            Key Takeaways: 
            {{key_takeaways}}

            {f"Use the below guidelines to generate an extensive, detailed, and in-depth summary: {detailed_summary_prompt}." if detailed_summary_prompt else "Use the below guidelines to generate an extensive, detailed, and in-depth summary."}

            Write a comprehensive, detailed, and in-depth summary of the entire document. 
            The summary should provide a thorough understanding of the document's contents, main ideas, action items, key takeaways and all other significant details.
            Cover the key aspects in depth in your long and comprehensive report.
            All sections must be detailed, comprehensive and in-depth. All sections must be rigorous, informative, easy to understand and follow.

            {math_formatting_instructions}

            Full document text:
            {{text}}

            Write the Comprehensive and In-depth Summary.
            """)
            llm_context = summary_prompt.format(
                document_type=document_type,
                key_aspects=key_aspects,
                key_takeaways=key_takeaways,
                detailed_summary_prompt=detailed_summary_prompt,
                text=text,
            )

        ans_generator = llm(llm_context, temperature=0.7, stream=True)
        method_ans_generator = None
        if (
            "arxiv" in self.doc_source
            or document_type
            in ["scientific paper", "research paper", "technical paper"]
            and False
        ):
            llm2_model = self.get_model_override(
                "doc_long_summary_model", CHEAP_LONG_CONTEXT_LLM[0]
            )
            llm2 = CallLLm(self.get_api_keys(), model_name=llm2_model)
            method_prompt = prompts.paper_details_map["methodology"]
            method_prompt += (
                "\n\n<context>\n"
                + text
                + f"\n</context>\n{math_formatting_instructions}\n\nWrite a detailed and comprehensive explanation of the methodology used in the paper covering the mathematical details as well as the intuition behind the methodology."
            )
            method_ans_generator = llm2(method_prompt, temperature=0.7, stream=True)

        for ans in ans_generator:
            long_summary += ans
            yield ans

        if (
            "arxiv" in self.doc_source
            or document_type
            in ["scientific paper", "research paper", "technical paper"]
            and method_ans_generator is not None
        ):
            long_summary += "\n\n ## More Details on their methodology \n"
            yield "\n\n ## More Details on their methodology \n"
            for ans in method_ans_generator:
                long_summary += ans
                yield ans
        setattr(self, "_long_summary", long_summary)
        self.save_local()

    def get_doc_long_summary_v2(
        self, model_name: str = None, aspects: List[str] = None
    ):
        """
        Generate a comprehensive multi-facet summary of the document.

        This method creates different types of summaries/analyses based on selected aspects.
        Uses the MultiFacetDocSummarizer class for the actual generation.

        Args:
            model_name: LLM model to use (default: CHEAP_LONG_CONTEXT_LLM[0])
            aspects: List of aspect IDs to include (default: all 6 aspects)
                     Options: "detailed", "facts_stats", "key_notes", "complex_faq",
                              "nitpicks", "agentic_qa"

        Yields:
            Formatted strings for each section of the multi-facet summary
        """
        if model_name is None:
            model_name = self.get_model_override(
                "doc_long_summary_v2_model", CHEAP_LONG_CONTEXT_LLM[0]
            )
        if aspects is None:
            aspects = [
                "detailed",
                "facts_stats",
                "key_notes",
                "complex_faq",
                "nitpicks",
                "agentic_qa",
            ]
        # Check if already cached (only for default full summary)
        cache_key = f"_long_summary_v2"
        if hasattr(self, cache_key):
            yield getattr(self, cache_key)
            return

        # Get the document text
        text = (
            self.brief_summary
            + "\n---\n"
            + self.get_doc_data("static_data", "doc_text")
        )

        # Create summarizer and generate
        summarizer = MultiFacetDocSummarizer(
            api_keys=self.get_api_keys(), model_name=model_name, aspects=aspects
        )

        full_summary = ""
        for chunk in summarizer.summarize(text):
            full_summary += chunk
            yield chunk

        # Cache the result
        setattr(self, cache_key, full_summary)
        self.save_local()

    def get_chain_of_density_summary(self):
        """Generate a high-density summary using chain-of-density technique adapted to document type."""

        if hasattr(self, "_dense_summary"):
            return self._dense_summary

        # Get base summary and document analysis
        if hasattr(self, "_long_summary"):
            base_summary = self._long_summary
        else:
            base_summary = make_stream(self.get_doc_long_summary(), False)

        density_model = self.get_model_override(
            "doc_long_summary_model", EXPENSIVE_LLM[0]
        )
        llm = CallLLm(self.get_api_keys(), model_name=density_model)
        if "arxiv" in self.doc_source:
            doc_analysis = json.loads("""
                                      {
                                            "doc_type": "scientific paper",
                                            "key_elements": [],
                                            "technical_level": "high",
                                            "summary_focus": [],
                                            "improvements": [],
                                            "missing_elements": []
                                        }
                                      """)
        else:
            # First determine document type and structure using the identification from long summary
            identify_prompt = dedent("""
            Analyze this summary and determine:
            1. The type of document (e.g., scientific paper, business report, technical documentation, news article, etc.)
            2. List the key aspects that should be included in a highly detailed and comprehensive summary for this type of document.
            3. The key structural elements that should be emphasized in a dense summary
            4. The appropriate level of technical detail needed
            5. List of improvements to be made to the summary
            6. List of missing elements from the summary

            Allowed document types:
            ```
            ["scientific paper", "research paper", "technical paper", "business report", "business proposal", "business plan", "technical documentation", "api documentation", "user manual", "other"]
            ```

            Summary text:
            {text}

            Only give JSON in your response in the format given below.

            Respond in JSON format:
            {{
                "doc_type": "type of document",
                "key_elements": ["list of important structural elements and key aspects for a detailed and comprehensive summary"],
                "technical_level": "high/medium/low",
                "summary_focus": ["specific aspects to focus on"],
                "improvements": ["list of improvements to be made to the summary"],
                "missing_elements": ["list of missing elements from the summary which could be added if present in the document"]
            }}
            """)

            json_response = llm(
                identify_prompt.format(text=base_summary), temperature=0.1, stream=False
            )
            logger.info(f"Chain of density identify response: \n{json_response}")
            doc_analysis = json.loads(json_response)

        # Select appropriate density prompt based on document type
        if doc_analysis["doc_type"] in [
            "scientific paper",
            "research paper",
            "technical paper",
        ]:
            density_prompt = prompts.scientific_chain_of_density_prompt
        elif doc_analysis["doc_type"] in [
            "business report",
            "business proposal",
            "business plan",
        ]:
            density_prompt = prompts.business_chain_of_density_prompt
        elif doc_analysis["doc_type"] in [
            "technical documentation",
            "api documentation",
            "user manual",
        ]:
            density_prompt = prompts.technical_chain_of_density_prompt
        else:
            density_prompt = prompts.general_chain_of_density_prompt

        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        # Initialize with first dense summary
        random_identifier = str(uuid.uuid4())
        answer = (
            f"\n\n**Summary {0 + 1} :** <div data-toggle='collapse' href='#summary-{random_identifier}-{0}' role='button'></div> <div class='collapse' id='summary-{random_identifier}-{0}'>\n"
            + base_summary
            + f"\n</div>\n\n"
        )
        yield answer
        preamble = f"\n\n**Final Summary :** <div data-toggle='collapse' href='#final-summary-{random_identifier}' role='button' aria-expanded='true'></div> <div class='collapse show' id='final-summary-{random_identifier}'>\n"
        answer += preamble
        yield preamble

        llm = CallLLm(self.get_api_keys(), model_name=CHEAP_LLM[0])

        generator = llm(
            density_prompt.format(
                text=text,
                previous_summaries=base_summary,
                iteration=1,
                doc_type=doc_analysis["doc_type"],
                key_elements=", ".join(doc_analysis["key_elements"]),
                technical_level=doc_analysis["technical_level"],
                improvements=", ".join(doc_analysis["improvements"]),
                missing_elements=", ".join(doc_analysis["missing_elements"]),
                PaperSummary=prompts.paper_summary_prompt,
            ),
            temperature=0.7,
            stream=True,
            system=prompts.chain_of_density_system_prompt,
        )
        for ans in generator:
            yield ans
            answer += ans
        answer += "\n</div>\n\n"
        yield f"\n</div>\n\n"

        all_summaries = [base_summary, answer]

        setattr(self, "_dense_summary", all_summaries[-1])
        self.save_local()
        random_identifier = str(uuid.uuid4())
        yield ""

    def semantic_search_document_small(self, query, token_limit=4096):
        st_time = time.time()
        tex_len = self.text_len
        stream1 = self.get_doc_long_summary()
        summary_text = (
            self.brief_summary + "\n---\n" + convert_stream_to_iterable(stream1)
        )
        summary_text_len = get_gpt4_word_count(summary_text)
        if tex_len + summary_text_len < token_limit:
            text = summary_text + self.get_doc_data("static_data", "doc_text")
            return text
        rem_word_len = max(
            0, token_limit - (self.brief_summary_len + len(summary_text.split()))
        )
        if rem_word_len <= 0:
            return summary_text
        rem_tokens = rem_word_len // self.chunk_size
        if self.raw_index_small is None:
            logger.warn(
                f"[semantic_search_document_small]:: Raw index small is None, returning using semantic_search_document fn."
            )
            return self.semantic_search_document(query, token_limit)
        raw_nodes = self.raw_index_small.similarity_search(
            query, k=max(self.result_cutoff, rem_tokens)
        )

        raw_text = "\n---\n".join(
            [
                f"Small Doc fragment {ix + 1}:\n{n.page_content}\n"
                for ix, n in enumerate(raw_nodes)
            ]
        )
        raw_text_len = get_gpt4_word_count(raw_text)
        logger.info(
            f"[semantic_search_document_small]:: Answered by {(time.time() - st_time):4f}s for additional info with additional_info_len = {raw_text_len}"
        )

        return summary_text + "\n---\n" + raw_text

    def semantic_search_document(self, query, token_limit=4096 * 4):
        # stacktrace = dump_stack()
        # logger.info(f"[semantic_search_document]:: Stack trace: \n{stacktrace}")
        st_time = time.time()
        tex_len = self.text_len
        stream1 = self.get_doc_long_summary()
        summary_text = (
            self.brief_summary + "\n---\n" + convert_stream_to_iterable(stream1)
        )
        stream2 = self.get_doc_long_summary_v2()
        ls2 = convert_stream_to_iterable(stream2)
        summary_text = summary_text + "\n---\n" + ls2 + "\n---\n"
        summary_text_len = get_gpt4_word_count(summary_text)
        if tex_len + summary_text_len < token_limit:
            text = summary_text + self.get_doc_data("static_data", "doc_text")
            return text
        rem_word_len = max(
            0, token_limit - (self.brief_summary_len + len(summary_text.split()))
        )
        if rem_word_len <= 0:
            return summary_text
        rem_tokens = rem_word_len // self.chunk_size
        if self.raw_index is None or tex_len < 8_000:
            text = summary_text + self.get_doc_data("static_data", "doc_text")
            logger.warn(
                f"[semantic_search_document]:: Raw index is None, returning brief summary and first chunk of text."
            )
            return chunk_text_words(text, chunk_size=token_limit, chunk_overlap=0)[0]
        raw_nodes = self.raw_index.similarity_search(
            query, k=max(self.result_cutoff, rem_tokens)
        )

        raw_text = "\n---\n".join(
            [
                f"Doc fragment {ix + 1}:\n{n.page_content}\n"
                for ix, n in enumerate(raw_nodes)
            ]
        )
        raw_text_len = get_gpt4_word_count(raw_text)
        logger.info(
            f"[semantic_search_document]:: Answered by {(time.time() - st_time):4f}s for additional info with additional_info_len = {raw_text_len}"
        )

        return summary_text + "\n---\n" + raw_text

    @streaming_timer
    def streaming_get_short_answer(
        self, query, mode=defaultdict(lambda: False), save_answer=True
    ):
        ent_time = time.time()
        detail_level = 1
        if mode["provide_detailed_answers"]:
            detail_level = max(1, int(mode["provide_detailed_answers"]))
            mode = "detailed"
        elif mode["review"]:
            mode = "detailed"
            detail_level = 2
        else:
            mode = None
            detail_level = 1

        # Sequential + RAG approach -> then combine.
        # For level 1, 2 both approaches use gpt3.5-16k -> gpt4-16k
        # For level 3, 4 both approaches use gpt3.5-16k + gpt4-16k

        additional_info = None
        stream1 = self.get_doc_long_summary()
        text = self.brief_summary + "\n---\n" + convert_stream_to_iterable(stream1)
        stream2 = self.get_doc_long_summary_v2()
        ls2 = convert_stream_to_iterable(stream2)
        text = (
            text
            + "\n---\n"
            + ls2
            + "\n---\n"
            + self.get_doc_data("static_data", "doc_text")
        )
        prompt = dedent(f"""
        Answer the question or query given below using the given context as reference. Ensure the answer contains all the facts and information from the document which is relevant to the question or query.
        If the question or query is not related to the document, then answer "This document does not contain information about that." or "No information can be derived about the user query from this document."
        Write all details you can derive from the document but in a short and concise manner like a note taker would write.
        Question or Query is given below.
        
        <|Query and Conversation Summary|>
        {query}
        <|/Query and Conversation Summary|>

        Write {"detailed and comprehensive " if detail_level >= 3 else "direct and concise "}answer.
        """)
        cr = ContextualReader(
            self.get_api_keys(), provide_short_responses=detail_level < 2
        )
        short_answer_model = self.get_model_override(
            "doc_short_answer_model", CHEAP_LONG_CONTEXT_LLM[0]
        )
        answer = get_async_future(
            cr, prompt, text, self.semantic_search_document, short_answer_model
        )
        if False:
            prompt2 = dedent(f"""
            Provide a critical, skeptical analysis of the document's ability to answer the question or query given below. 
            Focus on identifying gaps, inconsistencies, limitations, and areas where the document is insufficient or lacks depth.
            Question or Query is given below.
            
            <|Query and Conversation Summary|>
            {query}
            <|/Query and Conversation Summary|>

            Your task is to:
            1. Critically evaluate what the document LACKS in addressing this query, justifying with facts, numbers and evidence from the document.
            2. Point out any inconsistencies, contradictions, or unclear explanations
            3. Identify missing information, data, or evidence that would be needed for a complete answer
            4. Suggest what additional sources, research, or information would be required. Present the facts, numbers and evidence from the document that can help.
            5. Highlight any biases, assumptions, or methodological flaws in the document
            6. Provide constructive criticism on how the document could be improved to better address the query. What facts, numbers and evidence from the document can be improved or further explored to answer the query.
            7. Then write an answer for the question (with facts and anecdotes from the document) using the document as reference despite the limitations and gaps identified.
            8. Write in short and concise manner.

            Write a {"detailed and comprehensive " if detail_level >= 3 else ""}critical analysis focusing on limitations and gaps rather than what the document does well.
            """)
            cr2 = ContextualReader(
                self.get_api_keys(), provide_short_responses=detail_level < 2
            )
            sceptical_model = self.get_model_override(
                "doc_short_answer_model", VERY_CHEAP_LLM[0]
            )
            answer_sceptical = get_async_future(
                cr2, prompt2, text, self.semantic_search_document, sceptical_model
            )
        else:
            answer_sceptical = wrap_in_future(("", ""))

        tex_len = self.text_len
        answer = (
            sleep_and_get_future_result(answer)
            if sleep_and_get_future_exception(answer) is None
            else ""
        )
        answer, _ = answer
        answer_sceptical = (
            sleep_and_get_future_result(answer_sceptical)
            if sleep_and_get_future_exception(answer_sceptical) is None
            else ""
        )
        answer_sceptical, _ = answer_sceptical
        answer_sceptical = remove_bad_whitespaces(answer_sceptical)
        answer = remove_bad_whitespaces(answer)
        answer = answer + (
            (
                "\n\n<critical_analysis>\n"
                + answer_sceptical
                + "\n</critical_analysis>\n"
            )
            if len(answer_sceptical.strip()) > 0
            else ""
        )
        len_answer = len(re.findall(r"\S+", answer))
        for t in answer:
            yield t
        logger.info(
            f"[DocIndex] [streaming_get_short_answer] final_result len = {len(answer.split())} words."
        )
        yield ""

    def get_short_info(self):
        source = self.doc_source
        if self.is_local:
            # only give filename in source
            # source = os.path.basename(source)
            source = source.replace(os.path.dirname(__file__) + "/", "")
        return dict(
            visible=self.visible,
            doc_id=self.doc_id,
            source=source,
            title=self.title,
            short_summary=self.short_summary,
            summary=self.short_summary,
            display_name=getattr(self, "_display_name", None) or None,
        )

    @property
    def title(self):
        if hasattr(self, "_title") and len(self._title.strip()) > 0:
            return self._title
        elif self.doc_type == "image":
            return "image"
        else:
            title = CallLLm(self.get_api_keys(), model_name=VERY_CHEAP_LLM[0])(
                f"""Provide a title only for the below text: \n'{self.get_doc_data("raw_data", "chunks")[0]}' \nTitle: \n"""
            )
            setattr(self, "_title", title)
            self.save_local()
            return title

    @property
    def short_summary(self):
        if hasattr(self, "_short_summary") and len(self._short_summary.strip()) > 0:
            return self._short_summary
        elif self.doc_type == "image":
            return "image"
        else:
            short_summary = CallLLm(
                self.get_api_keys(), model_name=VERY_CHEAP_LLM[0], use_gpt4=False
            )(
                f"""Provide a summary for the below text: \n'''{self.get_doc_data("raw_data", "chunks")[0]}''' \nSummary: \n""",
            )
            setattr(self, "_short_summary", short_summary)
            self.save_local()
            return short_summary

    @staticmethod
    def load_local(folder):
        original_folder = folder
        folder = os.path.join(folder, os.path.basename(folder) + ".index")
        import dill

        try:
            with open(folder, "rb") as f:
                obj = dill.load(f)
                setattr(obj, "_storage", original_folder)
                return obj
        except Exception as e:
            logger.error(f"Error loading from local storage {folder} with error {e}")
            try:
                pass
                # shutil.rmtree(original_folder)
            except Exception as e:
                logger.error(f"Error deleting local storage {folder} with error {e}")
            return None

    def save_local(self):
        import dill

        doc_id = self.doc_id
        folder = self._storage
        os.makedirs(folder, exist_ok=True)
        os.makedirs(os.path.join(folder, "locks"), exist_ok=True)
        path = Path(folder)
        lock_location = os.path.join(
            os.path.join(path.parent.parent, "locks"), f"{doc_id}"
        )
        filepath = os.path.join(folder, f"{doc_id}.index")
        lock = FileLock(f"{lock_location}.lock")
        if hasattr(self, "api_keys"):
            presave_api_keys = self.api_keys
            self.api_keys = {k: None for k, v in self.api_keys.items()}

        with lock.acquire(timeout=600):
            previous_attr = dict()
            for k in self.store_separate:
                if hasattr(self, k):
                    previous_attr[k] = getattr(self, k)
                    setattr(self, k, None)
            with open(filepath, "wb") as f:
                dill.dump(self, f)
            for k, v in previous_attr.items():
                setattr(self, k, v)
        if hasattr(self, "api_keys"):
            self.api_keys = presave_api_keys

    def get_api_keys(self):
        logger.debug(
            f"get api keys for self hash = {hash(self)} and doc_id = {self.doc_id}"
        )
        if hasattr(self, "api_keys"):
            api_keys = deepcopy(self.api_keys)
        else:
            raise AttributeError("No attribute named `api_keys`.")
        return api_keys

    def set_api_keys(self, api_keys: dict):
        assert isinstance(api_keys, dict)
        logger.debug(
            f"set api keys for self hash = {hash(self)} and doc_id = {self.doc_id}"
        )
        indices = self.get_doc_data("indices")
        if indices is not None:
            for k, j in indices.items():
                if isinstance(j, (FAISS, VectorStore)):
                    j.embedding_function = get_embedding_model(api_keys).embed_query
                    if USE_OPENAI_API:
                        j.embedding_function.__self__.openai_api_key = api_keys[
                            "openAIKey"
                        ]
                        setattr(
                            j.embedding_function.__self__,
                            "openai_api_key",
                            api_keys["openAIKey"],
                        )
                    else:
                        j.embedding_function.__self__.openai_api_key = api_keys[
                            "jinaAIKey"
                        ]
                        setattr(
                            j.embedding_function.__self__,
                            "openai_api_key",
                            api_keys["jinaAIKey"],
                        )
        setattr(self, "api_keys", api_keys)

    def __copy__(self):
        # Create a new instance of our class
        cls = self.__class__
        result = cls.__new__(cls)
        # Copy all attributes from self to result. This is a shallow copy.
        result.__dict__.update(self.__dict__)
        for k in self.store_separate:
            if hasattr(result, k):
                setattr(result, k, None)

        if hasattr(result, "api_keys"):
            result.api_keys = deepcopy(self.api_keys)

        return result

    def copy(self):
        return self.__copy__()


class ImmediateDocIndex(DocIndex):
    pass


class FastDocIndex(DocIndex):
    """Lightweight document index using BM25 keyword search instead of FAISS embeddings.

    Purpose
    -------
    Provides a fast indexing path for documents attached to messages via drag-drop.
    Skips the expensive operations in the full ``DocIndex`` constructor (FAISS embedding
    creation, LLM-generated titles/summaries) and instead builds only a BM25 keyword
    index over text chunks.  This reduces upload latency from 15-45 seconds to 1-3 seconds.

    The document can later be "promoted" to a full ``ImmediateDocIndex`` (with FAISS
    embeddings and LLM summaries) when the user explicitly adds it to the conversation
    via the "Add to Conversation" context menu.

    Parameters
    ----------
    doc_source : str
        Path to the local file or remote URL.
    doc_filetype : str
        File type identifier (e.g. ``"pdf"``, ``"html"``, ``"md"``).
    doc_type : str
        Document category (e.g. ``"scientific_article"``).
    doc_text : str
        Full extracted text content of the document.
    chunk_size : int
        Number of words per chunk used during text splitting.
    chunks : list of str
        Pre-split text chunks for BM25 indexing.
    storage : str
        Parent directory where the document folder will be created.
    keys : dict
        API keys dict (stored but not used for any API calls during init).

    Attributes
    ----------
    _is_fast_index : bool
        Always ``True``; marker to distinguish from full ``DocIndex`` instances.
    _bm25_index : BM25Okapi or None
        BM25 index built from tokenized chunks.
    _bm25_chunks : list of str
        Raw chunk strings aligned with the BM25 index for retrieval.
    """

    def __init__(
        self,
        doc_source,
        doc_filetype,
        doc_type,
        doc_text,
        chunk_size,
        chunks,
        storage,
        keys,
    ):
        # ---- Deterministic doc ID (same hash as full DocIndex for same source) ----
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))

        self._visible = False
        self._chunk_size = chunk_size
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        self._is_fast_index = True
        self.init_complete = True

        # ---- Copy file into storage if needed (mirrors base DocIndex behaviour) ----
        if self.is_local and os.path.dirname(
            os.path.expanduser(doc_source)
        ) != os.path.expanduser(storage):
            try:
                shutil.move(doc_source, storage)
            except (shutil.Error, FileNotFoundError, OSError):
                # File may already be in storage (e.g. from a prior attempt that
                # partially succeeded) — try copy, then verify destination exists.
                dest = os.path.join(storage, os.path.basename(doc_source))
                if not os.path.exists(dest):
                    shutil.copy(doc_source, storage)
            doc_source = os.path.join(storage, os.path.basename(doc_source))

        self.doc_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type

        # ---- Title from filename (no LLM call) ----
        if self.is_local:
            self._title = os.path.splitext(os.path.basename(doc_source))[0]
        else:
            self._title = doc_source.rstrip("/").split("/")[-1]

        # ---- Summary from first 500 chars of text (no LLM call) ----
        self._short_summary = doc_text[:500].strip() if doc_text else ""
        self._display_name = None

        # ---- Storage folder ----
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = ["raw_data", "static_data"]

        # ---- Text metrics ----
        self._text_len = get_gpt4_word_count(doc_text) if doc_text else 0
        self._brief_summary = self._title + "\n" + self._short_summary
        self._brief_summary_len = get_gpt3_word_count(self._brief_summary)

        # ---- No FAISS indices ----
        self._raw_index = None
        self._raw_index_small = None

        # ---- BM25 index over chunks ----
        from rank_bm25 import BM25Okapi

        self._bm25_chunks = list(chunks) if chunks else []
        if len(self._bm25_chunks) > 0:
            tokenized = [c.lower().split() for c in self._bm25_chunks]
            self._bm25_index = BM25Okapi(tokenized)
        else:
            self._bm25_index = None

        # ---- Persist raw data and static data ----
        self.set_doc_data("raw_data", None, dict(chunks=self._bm25_chunks))
        self.set_doc_data(
            "static_data",
            None,
            dict(
                doc_source=doc_source,
                doc_filetype=doc_filetype,
                doc_type=doc_type,
                doc_text=doc_text,
            ),
        )

        self.set_api_keys(keys)
        self.save_local()

    # ---- Properties (override base to avoid LLM fallback calls) ----------------

    @property
    def title(self):
        return self._title

    @property
    def short_summary(self):
        return self._short_summary

    def set_api_keys(self, api_keys: dict):
        assert isinstance(api_keys, dict)
        setattr(self, "api_keys", api_keys)

    # ---- BM25 search -----------------------------------------------------------

    def bm25_search(self, query, top_k=10):
        """Search document chunks using BM25 keyword matching.

        Parameters
        ----------
        query : str
            The search query text.
        top_k : int, optional
            Maximum number of chunks to return (default 10).

        Returns
        -------
        list of str
            Top matching chunks sorted by descending BM25 score.
            Only chunks with score > 0 are returned.
        """
        if self._bm25_index is None or not self._bm25_chunks:
            return []
        tokenized_query = query.lower().split()
        scores = self._bm25_index.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
            :top_k
        ]
        return [self._bm25_chunks[i] for i in top_indices if scores[i] > 0]

    # ---- Override semantic search to use BM25 instead of FAISS -----------------

    def semantic_search_document(self, query, token_limit=4096 * 4):
        """BM25-based document search (replaces FAISS semantic search).

        For small documents whose full text fits within ``token_limit``, returns
        the complete text.  For larger documents, uses BM25 keyword matching to
        retrieve the most relevant chunks.

        Parameters
        ----------
        query : str
            The search query.
        token_limit : int, optional
            Maximum word budget for returned text (default 16384).

        Returns
        -------
        str
            Brief summary plus either full text or BM25-selected fragments.
        """
        doc_text = self.get_doc_data("static_data", "doc_text")
        if self._text_len < token_limit and doc_text:
            return self._brief_summary + "\n---\n" + doc_text

        chunk_budget = max(self.result_cutoff, token_limit // max(self._chunk_size, 1))
        results = self.bm25_search(query, top_k=chunk_budget)
        if not results:
            if doc_text:
                return chunk_text_words(
                    self._brief_summary + "\n---\n" + doc_text,
                    chunk_size=token_limit,
                    chunk_overlap=0,
                )[0]
            return self._brief_summary

        raw_text = "\n---\n".join(
            [f"Doc fragment {ix + 1}:\n{chunk}\n" for ix, chunk in enumerate(results)]
        )
        return self._brief_summary + "\n---\n" + raw_text

    def semantic_search_document_small(self, query, token_limit=4096):
        """BM25-based search with smaller token budget.

        Parameters
        ----------
        query : str
            The search query.
        token_limit : int, optional
            Maximum word budget (default 4096).

        Returns
        -------
        str
            Brief summary plus BM25-selected fragments.
        """
        return self.semantic_search_document(query, token_limit=token_limit)


class FastImageDocIndex(DocIndex):
    """Lightweight image document index that stores the image without LLM processing.

    Purpose
    -------
    Provides a fast path for image attachments in drag-drop message flows.  Unlike
    ``ImageDocIndex``, this class does NOT run OCR or vision-model captioning during
    construction.  It simply stores the image file and exposes ``llm_image_source``
    so that vision-capable models can see the image during the reply turn.

    The image can later be "promoted" to a full ``ImageDocIndex`` (with OCR, deep
    captioning, and FAISS embeddings) when the user adds it to the conversation.

    Parameters
    ----------
    doc_source : str
        Path to the local image file.
    doc_filetype : str
        Image type identifier (e.g. ``"jpg"``, ``"png"``).
    doc_type : str
        Always ``"image"`` for image documents.
    storage : str
        Parent directory where the document folder will be created.
    keys : dict
        API keys dict (stored but not used during init).

    Attributes
    ----------
    _is_fast_index : bool
        Always ``True``; marker to distinguish from full index instances.
    _llm_image_source : str
        Path to the original image for vision-model consumption.
    """

    def __init__(self, doc_source, doc_filetype, doc_type, storage, keys):
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))

        self._visible = False
        self._chunk_size = 0
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        self._is_fast_index = True
        self.init_complete = True

        # ---- Copy image to storage if needed ----
        if self.is_local and os.path.dirname(
            os.path.expanduser(doc_source)
        ) != os.path.expanduser(storage):
            try:
                shutil.move(doc_source, storage)
            except shutil.Error:
                shutil.copy(doc_source, storage)
            doc_source = os.path.join(storage, os.path.basename(doc_source))

        self.doc_source = doc_source
        self._llm_image_source = doc_source
        self.doc_filetype = doc_filetype
        self.doc_type = doc_type

        # ---- Title from filename ----
        self._title = (
            os.path.splitext(os.path.basename(doc_source))[0]
            if self.is_local
            else "image"
        )
        self._short_summary = "Image attachment"

        # ---- Storage folder ----
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = ["static_data"]

        # ---- No text, no indices ----
        self._text_len = 0
        self._brief_summary = self._title + "\n" + self._short_summary
        self._brief_summary_len = get_gpt3_word_count(self._brief_summary)
        self._raw_index = None
        self._raw_index_small = None
        self._bm25_index = None
        self._bm25_chunks = []

        # ---- Persist ----
        self.set_doc_data(
            "static_data",
            None,
            dict(
                doc_source=doc_source,
                doc_filetype=doc_filetype,
                doc_type=doc_type,
                doc_text="",
            ),
        )

        self.set_api_keys(keys)
        self.save_local()

    @property
    def llm_image_source(self):
        """Path to the original image file for vision-capable LLM calls."""
        return self._llm_image_source

    @property
    def title(self):
        return self._title

    @property
    def short_summary(self):
        return self._short_summary

    def set_api_keys(self, api_keys: dict):
        assert isinstance(api_keys, dict)
        setattr(self, "api_keys", api_keys)

    def semantic_search_document(self, query, token_limit=4096 * 4):
        """Return image reference for vision models (no text content available)."""
        return f"Image: {self._title}. Use vision model to analyze."

    def semantic_search_document_small(self, query, token_limit=4096):
        """Return image reference for vision models (no text content available)."""
        return self.semantic_search_document(query, token_limit=token_limit)

    def bm25_search(self, query, top_k=10):
        """No-op: images have no text chunks to search."""
        return []


class ImageDocIndex(DocIndex):
    def __init__(
        self,
        doc_source,
        doc_filetype,
        doc_type,
        doc_text,
        chunk_size,
        full_summary,
        openai_embed,
        storage,
        keys,
    ):
        init_start = time.time()
        self.doc_id = str(mmh3.hash(doc_source + doc_filetype + doc_type, signed=False))

        self._visible = False
        self._chunk_size = chunk_size
        self.result_cutoff = 4
        self.version = 0
        self.last_access_time = time.time()
        self.is_local = os.path.exists(doc_source)
        # if parent folder of doc_source is not same as storage, then copy the doc_source to storage
        if self.is_local and os.path.dirname(
            os.path.expanduser(doc_source)
        ) != os.path.expanduser(storage):
            # shutil.copy(doc_source, storage) # move not copy
            shutil.move(doc_source, storage)
            doc_source = os.path.join(storage, os.path.basename(doc_source))
            self.doc_source = doc_source

        # TODO: Convert image to pdf if it is an image, change the extension to pdf
        self.doc_source = doc_source
        # Keep a stable reference to the original image for vision-capable LLM calls.
        #
        # Why:
        # - Later in this initializer, we convert images to a PDF and overwrite `self.doc_source`
        #   with the generated PDF path for downstream indexing/storage.
        # - If callers (e.g., `Conversation.reply`) use `doc_source` as the image input, they
        #   will end up sending a PDF disguised as an image, which providers reject with
        #   "Could not process image".
        self._llm_image_source = doc_source

        self.doc_filetype = doc_filetype
        self.doc_type = doc_type
        self._title = ""
        self.init_complete = False
        self._short_summary = ""
        folder = os.path.join(storage, f"{self.doc_id}")
        os.makedirs(folder, exist_ok=True)
        self._storage = folder
        self.store_separate = ["indices", "raw_data", "static_data", "_paper_details"]
        assert doc_filetype in [
            "pdf",
            "word",
            "jpeg",
            "jpg",
            "png",
            "csv",
            "xls",
            "xlsx",
            "jpeg",
            "bmp",
            "svg",
            "parquet",
        ] and ("http" in doc_source or os.path.exists(doc_source))

        def complete_init_image_doc_index():
            llm = CallLLm(keys, use_gpt4=True, use_16k=True, model_name=CHEAP_LLM[0])
            llm2 = CallLLm(
                keys, use_gpt4=True, use_16k=True, model_name=CHEAP_LONG_CONTEXT_LLM[0]
            )
            doc_text_f1 = get_async_future(
                llm,
                prompts.deep_caption_prompt,
                images=[self.llm_image_source],
                stream=False,
            )
            doc_text_f2 = get_async_future(
                llm2,
                prompts.deep_caption_prompt,
                images=[self.llm_image_source],
                stream=False,
            )

            while not doc_text_f1.done() or not doc_text_f2.done():
                time.sleep(1)
            ocr_1 = (
                sleep_and_get_future_result(doc_text_f1)
                if sleep_and_get_future_exception(doc_text_f1) is None
                else ""
            )
            ocr_2 = (
                sleep_and_get_future_result(doc_text_f2)
                if sleep_and_get_future_exception(doc_text_f2) is None
                else ""
            )
            if len(ocr_1) > 0 and len(ocr_2) > 0:
                doc_text = (
                    "OCR and analysis from strong model:\n"
                    + ocr_1
                    + "\nOCR and analysis from weak model:\n"
                    + ocr_2
                )
            elif len(ocr_1) > 0:
                doc_text = "OCR and analysis from strong model:\n" + ocr_1
            elif len(ocr_2) > 0:
                doc_text = "OCR and analysis from weak model:\n" + ocr_2
            else:
                doc_text = "OCR failed."

            if (
                hasattr(self, "is_local")
                and self.is_local
                or "arxiv.org" not in self.doc_source
            ):

                def set_title_summary():
                    title = (
                        doc_text.split("</detailed_caption>")[0]
                        .split("<detailed_caption>")[-1]
                        .strip()
                    )
                    short_summary = (
                        doc_text.split("</detailed_insights>")[0]
                        .split("<detailed_insights>")[-1]
                        .strip()
                    )
                    setattr(self, "_title", title)
                    setattr(self, "_short_summary", short_summary)

                set_title_summary_future = get_async_future(set_title_summary)
            else:
                set_title_summary_future = wrap_in_future(None)
            static_data = dict(
                doc_source=doc_source,
                doc_filetype=doc_filetype,
                doc_type=doc_type,
                doc_text=doc_text,
            )
            del full_summary["chunks"]

            self.set_doc_data("static_data", None, static_data)
            time_logger.info(
                f"DocIndex init time without raw index: {(time.time() - init_start):.2f}"
            )
            self.set_api_keys(keys)

            def set_raw_index_small():
                _ = sleep_and_get_future_result(set_title_summary_future)
                brief_summary = self.title + "\n" + self.short_summary
                brief_summary = (
                    ("Summary:\n" + brief_summary + "\n\n")
                    if len(brief_summary.strip()) > 0
                    else ""
                )
                self._brief_summary = brief_summary
                text = self.brief_summary + doc_text
                self._text_len = get_gpt4_word_count(text)
                self._brief_summary_len = get_gpt3_word_count(brief_summary)
                time_logger.info(
                    f"DocIndex init time with raw index and title, summary: {(time.time() - init_start):.2f}"
                )

            set_raw_index_small()
            self.init_complete = True
            self.save_local()
            return True

        self.init_future = get_async_future(complete_init_image_doc_index)
        if doc_filetype in ["jpeg", "jpg", "png", "bmp", "svg"]:
            from img2pdf import convert

            pdf_path = os.path.splitext(doc_source)[0] + ".pdf"
            with open(doc_source, "rb") as f:
                image_data = f.read()
            with open(pdf_path, "wb") as f:
                f.write(convert(image_data))
            doc_source = pdf_path
            doc_filetype = "pdf"
        self.doc_source = doc_source

    @property
    def llm_image_source(self) -> str:
        """
        Return the best image path to use for vision-capable LLM calls.

        This intentionally prefers the original image file over `self.doc_source`,
        because `self.doc_source` may be rewritten to a PDF during initialization.
        """
        return getattr(self, "_llm_image_source", self.doc_source)

    def is_init_complete(self):
        # setattr that init_complete
        if hasattr(self, "init_complete"):
            return True

        return self.init_future.done()

    def wait_till_init_complete(self):
        while not self.init_complete:
            time.sleep(1)
        logger.info(
            f"Waited for init complete for Image doc id = {self.doc_id} with source = {self.doc_source}"
        )
        setattr(self, "init_complete", True)
        return True

    def semantic_search_document_small(self, query, token_limit=4096):
        return self.semantic_search_document(query, token_limit)

    def semantic_search_document(self, query, token_limit=4096):
        self.wait_till_init_complete()
        text = self.brief_summary + self.get_doc_data("static_data", "doc_text")
        return text

    @streaming_timer
    def streaming_get_short_answer(
        self, query, mode=defaultdict(lambda: False), save_answer=False
    ):
        self.wait_till_init_complete()
        doc_text = self.get_doc_data("static_data", "doc_text")
        text = self.brief_summary + doc_text
        if mode["provide_detailed_answers"] >= 3:
            llm = CallLLm(
                self.get_api_keys(), use_gpt4=True, model_name=EXPENSIVE_LLM[0]
            )
            prompt = """Please answer the user's query with the given image and the following text details of the image as context: \n\n'{}'\n\nConversation Details and User's Query: \n'{}'\n\nAnswer: \n""".format(
                text, query
            )
            answer = llm(
                prompt, images=[self.llm_image_source], temperature=0.7, stream=False
            )
            yield answer
        else:
            yield text


class YouTubeDocIndex(DocIndex):
    def __init__(
        self,
        doc_source,
        doc_filetype,
        doc_type,
        doc_text,
        chunk_size,
        full_summary,
        openai_embed,
        storage,
        keys,
    ):
        pass


AUDIO_FILE_EXTENSIONS = (
    ".mp3",
    ".mpeg",
    ".wav",
    ".wave",
    ".m4a",
    ".mp4",
    ".aac",
    ".flac",
    ".ogg",
    ".oga",
    ".opus",
    ".webm",
    ".wma",
    ".aiff",
    ".aif",
    ".aifc",
)


def _is_audio_file(path: str) -> bool:
    """Return True when the provided path has a supported audio extension."""
    return path.lower().endswith(AUDIO_FILE_EXTENSIONS)


def _transcribe_audio_document(audio_path: str, keys: dict) -> Tuple[str, str]:
    """Transcribe an audio file and persist the transcript as a PDF.

    Args:
        audio_path: Absolute path to the uploaded audio file.
        keys: API key dictionary associated with the current conversation.

    Returns:
        Tuple containing the raw transcript text and the PDF path that now
        houses the transcription.

    Raises:
        RuntimeError: If the transcription or PDF conversion fails.
    """
    transcription = transcribe_audio_file(
        audio_path,
        openai_api_key=keys.get("openAIKey"),
        assemblyai_api_key=keys.get("ASSEMBLYAI_API_KEY"),
    ).strip()

    if not transcription:
        transcription = "Transcription completed, but no text was returned."

    title = f"Transcript of {os.path.basename(audio_path)}"
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    markdown_body = (
        f"# {title}\n\n"
        f"- Original file: `{os.path.basename(audio_path)}`\n"
        f"- Generated at: {generated_at}\n\n"
        f"{transcription}"
    )

    pdf_output_path = os.path.splitext(audio_path)[0] + ".pdf"
    from converters import convert_markdown_string_to_pdf

    conversion_success = convert_markdown_string_to_pdf(
        markdown_body,
        pdf_output_path,
        title=title,
    )

    if not conversion_success:
        raise RuntimeError(f"Failed to convert transcription of {audio_path} to PDF.")

    return transcription, pdf_output_path


def create_immediate_document_index(pdf_url, folder, keys) -> DocIndex:
    from langchain_community.document_loaders import UnstructuredMarkdownLoader
    from langchain_community.document_loaders import JSONLoader
    from langchain_community.document_loaders import UnstructuredHTMLLoader
    from langchain_community.document_loaders.csv_loader import CSVLoader
    from langchain_community.document_loaders.tsv import UnstructuredTSVLoader
    from langchain_community.document_loaders import UnstructuredWordDocumentLoader
    from langchain_community.document_loaders import TextLoader
    from langchain_community.document_loaders import YoutubeLoader
    import pandas as pd

    is_image = False
    image_futures = None
    chunk_overlap = 128
    pdf_url = pdf_url.strip()
    lower_pdf_url = pdf_url.lower()
    # check if the link is local or remote
    is_remote = (
        pdf_url.startswith("http")
        or pdf_url.startswith("ftp")
        or pdf_url.startswith("s3")
        or pdf_url.startswith("gs")
        or pdf_url.startswith("azure")
        or pdf_url.startswith("https")
        or pdf_url.startswith("www.")
    )
    assert is_remote or os.path.exists(pdf_url), f"File {pdf_url} does not exist"
    if is_remote:
        pdf_url = convert_to_pdf_link_if_needed(pdf_url)
        is_pdf = is_pdf_link(pdf_url)
    else:
        is_pdf = lower_pdf_url.endswith(".pdf")
    # based on extension of the pdf_url decide on the loader to use, in case no extension is present then try pdf, word, html, markdown in that order.
    logger.info(
        f"Creating immediate doc index for {pdf_url}, is_remote = {is_remote}, is_pdf = {is_pdf}"
    )
    if is_pdf:
        filetype = "pdf"
    elif lower_pdf_url.endswith(".docx"):
        filetype = "word"
    elif lower_pdf_url.endswith(".html"):
        filetype = "html"
    elif lower_pdf_url.endswith(".md"):
        filetype = "md"
    elif lower_pdf_url.endswith(".json"):
        filetype = "json"
    elif lower_pdf_url.endswith(".csv"):
        filetype = "csv"
    elif lower_pdf_url.endswith(".txt"):
        filetype = "txt"
    elif lower_pdf_url.endswith(".jpg"):
        filetype = "jpg"
    elif lower_pdf_url.endswith(".png"):
        filetype = "png"
    elif lower_pdf_url.endswith(".jpeg"):
        filetype = "jpeg"
    elif lower_pdf_url.endswith(".bmp"):
        filetype = "bmp"
    elif lower_pdf_url.endswith(".svg"):
        filetype = "svg"
    elif _is_audio_file(pdf_url):
        filetype = "audio"
    else:
        filetype = "pdf"
    if is_pdf:
        doc_text = PDFReaderTool(keys)(pdf_url)
    elif pdf_url.endswith(".docx"):
        doc_text = UnstructuredWordDocumentLoader(pdf_url).load()[0].page_content
        from converters import convert_doc_to_pdf

        convert_doc_to_pdf(pdf_url, pdf_url.replace(".docx", ".pdf"))
        pdf_url = pdf_url.replace(".docx", ".pdf")
    elif (
        is_remote
        and (
            "https://www.youtube.com/watch?v" in pdf_url
            or "https://www.youtube.com/shorts/" in pdf_url
            or is_youtube_link(pdf_url)
        )
        and False
    ):
        doc_text = YoutubeLoader.from_youtube_url(pdf_url, add_video_info=False).load()
        doc_text = "\n".join([d.page_content for d in doc_text])

    elif is_remote and is_youtube_link(pdf_url):
        temp_folder = os.path.join(os.getcwd(), "temp")
        if not os.path.exists(temp_folder):
            os.makedirs(temp_folder)
        from YouTubeDocIndex import answer_youtube_question

        result = answer_youtube_question(
            "",
            pdf_url,
            keys["ASSEMBLYAI_API_KEY"],
            keys["OPENROUTER_API_KEY"],
            temp_folder,
        )
        doc_text = (
            result["transcript"] + "\n" + result["summary"] + "\n" + result["subtitles"]
        )

    elif is_remote and not (
        pdf_url.endswith(".md")
        or pdf_url.endswith(".json")
        or pdf_url.endswith(".csv")
        or pdf_url.endswith(".txt")
    ):
        html = fetch_html(pdf_url, keys["zenrows"], keys["brightdataUrl"])
        # save this html to a file and then use the html loader.
        html_file = os.path.join(folder, "temp.html")
        with open(html_file, "w") as f:
            f.write(html)
        from converters import convert_html_to_pdf

        convert_html_to_pdf(html_file, html_file.replace(".html", ".pdf"))
        pdf_url = html_file.replace(".html", ".pdf")
        # delete html file
        os.remove(html_file)
        doc_text = UnstructuredHTMLLoader(html_file).load()[0].page_content
    elif pdf_url.endswith(".html"):
        from converters import convert_html_to_pdf

        doc_text = UnstructuredHTMLLoader(pdf_url).load()[0].page_content
        convert_html_to_pdf(pdf_url, pdf_url.replace(".html", ".pdf"))
        pdf_url = pdf_url.replace(".html", ".pdf")

    elif pdf_url.endswith(".md"):
        doc_text = UnstructuredMarkdownLoader(pdf_url).load()[0].page_content
        from converters import convert_markdown_to_pdf

        convert_markdown_to_pdf(pdf_url, pdf_url.replace(".md", ".pdf"))
        pdf_url = pdf_url.replace(".md", ".pdf")

    elif _is_audio_file(pdf_url):
        if is_remote:
            raise ValueError(
                "Remote audio URLs are not supported. Please upload the audio file directly."
            )
        doc_text, pdf_url = _transcribe_audio_document(pdf_url, keys)
        is_pdf = True
    elif pdf_url.endswith(".json"):
        doc_text = JSONLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".csv"):
        df = pd.read_csv(pdf_url, engine="python")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".tsv"):
        df = pd.read_csv(pdf_url, sep="\t")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".parquet"):
        df = pd.read_parquet(pdf_url)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".xlsx") or pdf_url.endswith(".xls"):
        df = pd.read_excel(pdf_url, engine="openpyxl")
        doc_text = df.to_markdown()
    elif pdf_url.endswith(".jsonlines") or pdf_url.endswith(".jsonl"):
        df = pd.read_json(pdf_url, lines=True)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".json"):
        df = pd.read_json(pdf_url)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".txt"):
        doc_text = TextLoader(pdf_url).load()[0].page_content
        from converters import convert_markdown_to_pdf

        convert_markdown_to_pdf(pdf_url, pdf_url.replace(".txt", ".pdf"))
        pdf_url = pdf_url.replace(".txt", ".pdf")
    elif (
        pdf_url.endswith(".jpg")
        or pdf_url.endswith(".jpeg")
        or pdf_url.endswith(".png")
        or pdf_url.endswith(".bmp")
        or pdf_url.endswith(".svg")
    ):
        doc_text = ""
        is_image = True
        chunk_overlap = 0
    else:
        raise Exception(f"Could not find a suitable loader for the given url {pdf_url}")

    doc_text = (
        doc_text.replace("<|endoftext|>", "\n")
        .replace("endoftext", "end_of_text")
        .replace("<|endoftext|>", "")
    )
    doc_text_len = len(doc_text.split())
    if doc_text_len < 16000:
        chunk_size = LARGE_CHUNK_LEN // 8
    elif doc_text_len < 128_000:
        chunk_size = LARGE_CHUNK_LEN // 4
    else:
        chunk_size = LARGE_CHUNK_LEN // 2
    chunk_overlap = min(chunk_size // 2, 128)
    chunk_size = max(chunk_size, chunk_overlap * 2)
    if not is_image:
        chunks = get_async_future(
            chunk_text_words,
            doc_text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        chunks_small = get_async_future(
            chunk_text_words,
            doc_text,
            chunk_size=chunk_size // 2,
            chunk_overlap=chunk_overlap,
        )
        # chunks = get_async_future(ChunkText, doc_text, chunk_size, 64)
        # chunks_small = get_async_future(ChunkText, doc_text, chunk_size//2, 64)
        chunks = sleep_and_get_future_result(chunks)
        chunks_small = sleep_and_get_future_result(chunks_small)
    else:
        chunks = []
        chunks_small = []
    nested_dict = {
        "chunks": chunks,
        "chunks_small": chunks_small,
        "image_futures": image_futures,
    }
    openai_embed = get_embedding_model(keys)
    cls = ImmediateDocIndex if not is_image else ImageDocIndex
    try:
        doc_index: DocIndex = cls(
            pdf_url,
            filetype
            if filetype
            in [
                "pdf",
                "html",
                "word",
                "docx",
                "jpeg",
                "md",
                "jpg",
                "png",
                "csv",
                "xls",
                "xlsx",
                "bmp",
                "svg",
                "parquet",
            ]
            else "pdf",
            "scientific_article" if not is_image else "image",
            doc_text,
            chunk_size,
            nested_dict,
            openai_embed,
            folder,
            keys,
        )
        # for k in doc_index.store_separate:
        #     doc_index.set_doc_data(k, None, doc_index.get_doc_data(k), overwrite=True)
        doc_index.set_api_keys(keys)

        def get_doc_ready():
            return doc_index.get_short_info()

        _ = get_async_future(get_doc_ready)
        doc_index._visible = True
    except Exception as e:
        doc_id = str(mmh3.hash(pdf_url + "pdf" + "scientific_article", signed=False))
        try:
            folder = os.path.join(folder, f"{doc_id}")
            if os.path.exists(folder):
                shutil.rmtree(folder)
        except Exception as e:
            pass
        logger.error(f"Error creating immediate doc index for {pdf_url}")
        raise e

    return doc_index


def create_fast_document_index(pdf_url, folder, keys) -> DocIndex:
    """Create a lightweight document index with BM25 search (no FAISS embeddings).

    Performs the same text extraction and chunking as ``create_immediate_document_index``
    but skips FAISS embedding creation, LLM-generated summaries, and other expensive
    operations.  Returns a ``FastDocIndex`` (for text documents) or ``FastImageDocIndex``
    (for images) that can later be promoted to a full index.

    Parameters
    ----------
    pdf_url : str
        Local file path or remote URL of the document.
    folder : str
        Parent storage directory for the resulting index.
    keys : dict
        API keys dict (used for text extraction loaders, NOT for embeddings/LLM).

    Returns
    -------
    DocIndex
        A ``FastDocIndex`` or ``FastImageDocIndex`` instance, saved to disk.
    """
    from langchain_community.document_loaders import UnstructuredMarkdownLoader
    from langchain_community.document_loaders import JSONLoader
    from langchain_community.document_loaders import UnstructuredHTMLLoader
    from langchain_community.document_loaders.csv_loader import CSVLoader
    from langchain_community.document_loaders.tsv import UnstructuredTSVLoader
    from langchain_community.document_loaders import UnstructuredWordDocumentLoader
    from langchain_community.document_loaders import TextLoader
    import pandas as pd

    is_image = False
    pdf_url = pdf_url.strip()
    lower_pdf_url = pdf_url.lower()

    # ---- Detect local vs remote ----
    is_remote = (
        pdf_url.startswith("http")
        or pdf_url.startswith("ftp")
        or pdf_url.startswith("s3")
        or pdf_url.startswith("gs")
        or pdf_url.startswith("azure")
        or pdf_url.startswith("https")
        or pdf_url.startswith("www.")
    )
    assert is_remote or os.path.exists(pdf_url), f"File {pdf_url} does not exist"
    if is_remote:
        pdf_url = convert_to_pdf_link_if_needed(pdf_url)
        is_pdf = is_pdf_link(pdf_url)
    else:
        is_pdf = lower_pdf_url.endswith(".pdf")

    logger.info(
        f"Creating fast doc index for {pdf_url}, is_remote = {is_remote}, is_pdf = {is_pdf}"
    )

    # ---- File type detection (same logic as create_immediate_document_index) ----
    if is_pdf:
        filetype = "pdf"
    elif lower_pdf_url.endswith(".docx"):
        filetype = "word"
    elif lower_pdf_url.endswith(".html"):
        filetype = "html"
    elif lower_pdf_url.endswith(".md"):
        filetype = "md"
    elif lower_pdf_url.endswith(".json"):
        filetype = "json"
    elif lower_pdf_url.endswith(".csv"):
        filetype = "csv"
    elif lower_pdf_url.endswith(".txt"):
        filetype = "txt"
    elif lower_pdf_url.endswith(".jpg"):
        filetype = "jpg"
    elif lower_pdf_url.endswith(".png"):
        filetype = "png"
    elif lower_pdf_url.endswith(".jpeg"):
        filetype = "jpeg"
    elif lower_pdf_url.endswith(".bmp"):
        filetype = "bmp"
    elif lower_pdf_url.endswith(".svg"):
        filetype = "svg"
    elif _is_audio_file(pdf_url):
        filetype = "audio"
    else:
        filetype = "pdf"

    # ---- Image fast path: no text extraction, no LLM ----
    if filetype in ("jpg", "jpeg", "png", "bmp", "svg"):
        is_image = True
        valid_filetypes = [
            "pdf",
            "html",
            "word",
            "docx",
            "jpeg",
            "md",
            "jpg",
            "png",
            "csv",
            "xls",
            "xlsx",
            "bmp",
            "svg",
            "parquet",
        ]
        ft = filetype if filetype in valid_filetypes else "pdf"
        try:
            doc_index = FastImageDocIndex(pdf_url, ft, "image", folder, keys)
            doc_index._visible = True
            return doc_index
        except Exception as e:
            logger.error(f"Error creating fast image doc index for {pdf_url}")
            raise e

    # ---- Text extraction (same loaders as create_immediate_document_index) ----
    if is_pdf:
        doc_text = PDFReaderTool(keys)(pdf_url)
    elif pdf_url.endswith(".docx"):
        doc_text = UnstructuredWordDocumentLoader(pdf_url).load()[0].page_content
    elif is_remote and not (
        pdf_url.endswith(".md")
        or pdf_url.endswith(".json")
        or pdf_url.endswith(".csv")
        or pdf_url.endswith(".txt")
    ):
        html = fetch_html(pdf_url, keys["zenrows"], keys["brightdataUrl"])
        html_file = os.path.join(folder, "temp_fast.html")
        with open(html_file, "w") as f:
            f.write(html)
        doc_text = UnstructuredHTMLLoader(html_file).load()[0].page_content
        try:
            os.remove(html_file)
        except OSError:
            pass
    elif pdf_url.endswith(".html"):
        doc_text = UnstructuredHTMLLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".md"):
        doc_text = UnstructuredMarkdownLoader(pdf_url).load()[0].page_content
    elif _is_audio_file(pdf_url):
        if is_remote:
            raise ValueError(
                "Remote audio URLs are not supported. Please upload the audio file directly."
            )
        doc_text, pdf_url = _transcribe_audio_document(pdf_url, keys)
    elif pdf_url.endswith(".json"):
        doc_text = JSONLoader(pdf_url).load()[0].page_content
    elif pdf_url.endswith(".csv"):
        df = pd.read_csv(pdf_url, engine="python")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".tsv"):
        df = pd.read_csv(pdf_url, sep="\t")
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".parquet"):
        df = pd.read_parquet(pdf_url)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".xlsx") or pdf_url.endswith(".xls"):
        df = pd.read_excel(pdf_url, engine="openpyxl")
        doc_text = df.to_markdown()
    elif pdf_url.endswith(".jsonlines") or pdf_url.endswith(".jsonl"):
        df = pd.read_json(pdf_url, lines=True)
        doc_text = df.sample(min(len(df), 10)).to_markdown()
    elif pdf_url.endswith(".txt"):
        doc_text = TextLoader(pdf_url).load()[0].page_content
    else:
        raise Exception(f"Could not find a suitable loader for the given url {pdf_url}")

    # ---- Clean text ----
    doc_text = (
        doc_text.replace("<|endoftext|>", "\n")
        .replace("endoftext", "end_of_text")
        .replace("<|endoftext|>", "")
    )

    # ---- Chunking (same sizing logic as create_immediate_document_index) ----
    doc_text_len = len(doc_text.split())
    if doc_text_len < 16000:
        chunk_size = LARGE_CHUNK_LEN // 8
    elif doc_text_len < 128_000:
        chunk_size = LARGE_CHUNK_LEN // 4
    else:
        chunk_size = LARGE_CHUNK_LEN // 2
    chunk_overlap = min(chunk_size // 2, 128)
    chunk_size = max(chunk_size, chunk_overlap * 2)

    chunks = chunk_text_words(
        doc_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    # ---- Create FastDocIndex (BM25 only, no FAISS/LLM) ----
    valid_filetypes = [
        "pdf",
        "html",
        "word",
        "docx",
        "jpeg",
        "md",
        "jpg",
        "png",
        "csv",
        "xls",
        "xlsx",
        "bmp",
        "svg",
        "parquet",
    ]
    ft = filetype if filetype in valid_filetypes else "pdf"
    try:
        doc_index = FastDocIndex(
            pdf_url,
            ft,
            "scientific_article",
            doc_text,
            chunk_size,
            chunks,
            folder,
            keys,
        )
        doc_index._visible = True
        return doc_index
    except Exception as e:
        doc_id = str(mmh3.hash(pdf_url + ft + "scientific_article", signed=False))
        try:
            cleanup_folder = os.path.join(folder, f"{doc_id}")
            if os.path.exists(cleanup_folder):
                shutil.rmtree(cleanup_folder)
        except Exception:
            pass
        logger.error(f"Error creating fast doc index for {pdf_url}")
        raise e


# =============================================================================
# Multi-Document Answer Agent
# =============================================================================


class MultiDocAnswerAgent:
    """
    An agent that answers queries using multiple DocIndex documents.

    This agent gathers context from multiple documents, reformulates queries for
    better comprehension, and synthesizes answers from all document sources.
    Supports two detail levels for varying depth of response.

    Flow:
    1. Reformulate user query based on query, conversation context, and doc summaries
    2. Query each DocIndex in parallel with the reformulated query
    3. Synthesize all answers into a final response
    4. If detail_level=1, do a second pass for additional justification and depth

    Usage:
        agent = MultiDocAnswerAgent(docs=[doc1, doc2], model_name="gpt-4", detail_level=1)
        for chunk in agent(query="What is X?", conversation_summary="We discussed Y"):
            print(chunk)
    """

    # Token limit for context (using tiktoken gpt-4 encoder)
    MAX_CONTEXT_TOKENS = 150_000

    def __init__(
        self,
        docs: List["DocIndex"],
        api_keys: dict,
        model_name: str = None,
        detail_level: int = 0,
    ):
        """
        Initialize the multi-document answer agent.

        Args:
            docs: List of DocIndex objects to query
            api_keys: Dictionary containing API keys for LLM services
            model_name: LLM model to use (default: CHEAP_LONG_CONTEXT_LLM[0])
            detail_level: 0 for single-pass answer, 1 for two-pass with justification
        """
        if not docs:
            raise ValueError("At least one DocIndex must be provided")

        self.docs = docs
        self.api_keys = api_keys
        self.model_name = model_name or CHEAP_LONG_CONTEXT_LLM[0]
        self.detail_level = detail_level

        # Initialize tiktoken encoder for token counting
        import tiktoken

        self.encoder = tiktoken.encoding_for_model("gpt-4")

    def _count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken."""
        return len(self.encoder.encode(text))

    def _get_llm(self, model_name: str = None):
        """Get a configured LLM instance."""
        return CallLLm(self.api_keys, model_name=model_name or self.model_name)

    def _get_doc_summaries(self) -> str:
        """Get brief summaries from all documents."""
        summaries = []
        for i, doc in enumerate(self.docs):
            title = getattr(doc, "title", f"Document {i + 1}")
            brief = doc.brief_summary if hasattr(doc, "brief_summary") else ""
            summaries.append(f"**Document {i + 1}: {title}**\n{brief}")
        return "\n\n".join(summaries)

    def _reformulate_query(
        self,
        query: str,
        conversation_summary: str = None,
        conversation_history: str = None,
    ) -> str:
        """
        Reformulate the user query to be more detailed and elaborate.

        Uses the original query, conversation context, and document summaries
        to create a more comprehensive query for document search.

        Args:
            query: Original user query
            conversation_summary: Optional summary of conversation so far
            conversation_history: Optional full conversation history

        Returns:
            Reformulated, more detailed query
        """
        doc_summaries = self._get_doc_summaries()

        context_parts = []
        if conversation_summary:
            context_parts.append(f"**Conversation Summary:**\n{conversation_summary}")
        if conversation_history:
            context_parts.append(f"**Recent Conversation:**\n{conversation_history}")

        context_str = (
            "\n\n".join(context_parts)
            if context_parts
            else "No prior conversation context."
        )

        prompt = dedent(f"""
        You are a query reformulation expert. Your task is to take a user's query and reformulate it 
        into a more detailed, comprehensive question that will help retrieve better information from documents.
        
        **Available Documents:**
        {doc_summaries}
        
        **Conversation Context:**
        {context_str}
        
        **Original User Query:**
        {query}
        
        **Instructions:**
        1. Expand the query to be more specific and detailed
        2. Include relevant context from the conversation if applicable
        3. Consider what aspects of the documents might be relevant
        4. Make the query self-contained (understandable without conversation context)
        5. Keep the reformulated query focused but comprehensive
        
        **Reformulated Query:**
        """)

        llm = self._get_llm(CHEAP_LLM[0])
        reformulated = llm(prompt, temperature=0.3, stream=False)
        return reformulated.strip()

    def _query_docs_parallel(
        self, query: str, mode: dict = None
    ) -> List[Tuple[str, str]]:
        """
        Query all documents in parallel and gather their answers.

        Args:
            query: The query to send to each document
            mode: Optional mode dict for get_short_answer

        Returns:
            List of (doc_title, answer) tuples
        """
        if mode is None:
            mode = defaultdict(lambda: False)
            mode["provide_detailed_answers"] = 2

        # Launch all queries in parallel
        futures = []
        for doc in self.docs:
            future = get_async_future(doc.get_short_answer, query, mode)
            futures.append((doc, future))

        # Gather results
        results = []
        for doc, future in futures:
            try:
                answer = sleep_and_get_future_result(future)
                title = getattr(doc, "title", doc.doc_source)
                results.append((title, answer))
            except Exception as e:
                title = getattr(doc, "title", doc.doc_source)
                results.append((title, f"Error retrieving answer: {str(e)}"))
                logger.error(f"Error querying doc {title}: {e}")

        return results

    def _format_doc_answers(self, doc_answers: List[Tuple[str, str]]) -> str:
        """Format document answers for inclusion in prompts."""
        formatted = []
        for i, (title, answer) in enumerate(doc_answers):
            formatted.append(f"### Source {i + 1}: {title}\n\n{answer}")
        return "\n\n---\n\n".join(formatted)

    def _can_include_history(
        self,
        query: str,
        doc_answers_text: str,
        conversation_summary: str = None,
        conversation_history: str = None,
    ) -> bool:
        """
        Check if conversation history can be included within token limit.

        Args:
            query: Reformulated query
            doc_answers_text: Formatted document answers
            conversation_summary: Conversation summary
            conversation_history: Full conversation history

        Returns:
            True if history can be included, False otherwise
        """
        total_tokens = self._count_tokens(query)
        total_tokens += self._count_tokens(doc_answers_text)
        if conversation_summary:
            total_tokens += self._count_tokens(conversation_summary)
        if conversation_history:
            total_tokens += self._count_tokens(conversation_history)

        # Leave room for prompt template and response
        return total_tokens < (self.MAX_CONTEXT_TOKENS - 10000)

    def _generate_final_answer(
        self,
        reformulated_query: str,
        doc_answers: List[Tuple[str, str]],
        conversation_summary: str = None,
        conversation_history: str = None,
        previous_answer: str = None,
        is_refinement: bool = False,
    ) -> str:
        """
        Generate the final synthesized answer from all document sources.

        Args:
            reformulated_query: The reformulated user query
            doc_answers: List of (title, answer) tuples from each document
            conversation_summary: Optional conversation summary
            conversation_history: Optional conversation history
            previous_answer: Previous answer (for refinement pass)
            is_refinement: Whether this is a refinement/justification pass

        Returns:
            Synthesized final answer
        """
        doc_answers_text = self._format_doc_answers(doc_answers)

        # Check if we can include history
        include_history = self._can_include_history(
            reformulated_query,
            doc_answers_text,
            conversation_summary,
            conversation_history,
        )

        # Build context sections
        context_parts = []
        if conversation_summary:
            context_parts.append(f"**Conversation Summary:**\n{conversation_summary}")
        if include_history and conversation_history:
            context_parts.append(f"**Conversation History:**\n{conversation_history}")
        elif conversation_history and not include_history:
            context_parts.append("*(Conversation history omitted due to length)*")

        context_str = "\n\n".join(context_parts) if context_parts else ""

        if is_refinement and previous_answer:
            prompt = dedent(f"""
            You are an expert analyst synthesizing information from multiple document sources.
            
            **User Query:**
            {reformulated_query}
            
            {f"**Context:**{chr(10)}{context_str}" if context_str else ""}
            
            **Previous Answer:**
            {previous_answer}
            
            **Additional Information and Justifications from Documents:**
            {doc_answers_text}
            
            **Instructions:**
            1. Review the previous answer and the additional document information
            2. Incorporate new details, evidence, and justifications
            3. Correct any inaccuracies found in the previous answer
            4. Provide specific citations and references from the documents
            5. Create a comprehensive, well-supported final answer
            6. Maintain clear structure with sections if appropriate
            
            {math_formatting_instructions}
            
            **Refined Final Answer:**
            """)
        else:
            prompt = dedent(f"""
            You are an expert analyst synthesizing information from multiple document sources.
            
            **User Query:**
            {reformulated_query}
            
            {f"**Context:**{chr(10)}{context_str}" if context_str else ""}
            
            **Information from Documents:**
            {doc_answers_text}
            
            **Instructions:**
            1. Synthesize information from all document sources
            2. Provide a comprehensive, coherent answer to the query
            3. Cite specific sources when making claims
            4. Note any contradictions or gaps between sources
            5. Structure the answer clearly with sections if appropriate
            6. Be thorough but concise
            
            {math_formatting_instructions}
            
            **Answer:**
            """)

        llm = self._get_llm()
        return llm(prompt, temperature=0.5, stream=False)

    def _get_justification_answers(
        self, reformulated_query: str, previous_answer: str
    ) -> List[Tuple[str, str]]:
        """
        Query documents for additional justification and details based on previous answer.

        Args:
            reformulated_query: The reformulated query
            previous_answer: The initial answer to justify/expand

        Returns:
            List of (doc_title, justification) tuples
        """
        justification_query = dedent(f"""
        Based on the following query and initial answer, provide additional information, 
        evidence, and justification from your content. Focus on:
        1. Supporting evidence for claims made in the answer
        2. Additional relevant details not covered
        3. Any contradictory information or caveats
        4. Specific data, quotes, or references
        
        **Original Query:**
        {reformulated_query}
        
        **Initial Answer to Justify/Expand:**
        {previous_answer}
        
        **Provide additional information and justification:**
        """)

        mode = defaultdict(lambda: False)
        mode["provide_detailed_answers"] = 3  # Higher detail for justification

        return self._query_docs_parallel(justification_query, mode)

    def __call__(
        self,
        query: str,
        conversation_summary: str = None,
        conversation_history: str = None,
    ):
        """
        Answer a query using multiple documents.

        This is the main entry point. It reformulates the query, queries all documents
        in parallel, and synthesizes a final answer. If detail_level=1, performs a
        second pass for additional justification.

        Args:
            query: User's question or query
            conversation_summary: Optional summary of conversation so far
            conversation_history: Optional full conversation history text

        Yields:
            Chunks of the answer as they are generated
        """
        # Step 1: Reformulate the query
        yield "🔄 *Reformulating query for comprehensive search...*\n\n"

        reformulated_query = self._reformulate_query(
            query, conversation_summary, conversation_history
        )

        yield f"**Reformulated Query:**\n> {reformulated_query}\n\n"
        yield "---\n\n"

        # Step 2: Query all documents in parallel
        yield f"📚 *Querying {len(self.docs)} document(s)...*\n\n"

        doc_answers = self._query_docs_parallel(reformulated_query)

        yield f"✅ *Received answers from {len(doc_answers)} document(s)*\n\n"
        yield "---\n\n"

        # Step 3: Generate initial synthesized answer
        yield "🧠 *Synthesizing answer from all sources...*\n\n"

        initial_answer = self._generate_final_answer(
            reformulated_query=reformulated_query,
            doc_answers=doc_answers,
            conversation_summary=conversation_summary,
            conversation_history=conversation_history,
            is_refinement=False,
        )

        # If detail_level is 0, we're done
        if self.detail_level == 0:
            yield "## Answer\n\n"
            yield initial_answer
            return

        # Step 4: For detail_level 1, do refinement pass
        yield "## Initial Answer\n\n"
        yield initial_answer
        yield "\n\n---\n\n"
        yield "🔍 *Gathering additional justification and details...*\n\n"

        # Query documents again for justification
        justification_answers = self._get_justification_answers(
            reformulated_query, initial_answer
        )

        yield f"✅ *Received additional context from {len(justification_answers)} document(s)*\n\n"
        yield "---\n\n"

        # Step 5: Generate refined final answer
        yield "🎯 *Generating refined answer with additional justification...*\n\n"

        refined_answer = self._generate_final_answer(
            reformulated_query=reformulated_query,
            doc_answers=justification_answers,
            conversation_summary=conversation_summary,
            conversation_history=conversation_history,
            previous_answer=initial_answer,
            is_refinement=True,
        )

        yield "## Refined Answer (with Justification)\n\n"
        yield refined_answer

    def answer_sync(
        self,
        query: str,
        conversation_summary: str = None,
        conversation_history: str = None,
    ) -> str:
        """
        Answer a query synchronously (non-streaming).

        Args:
            query: User's question or query
            conversation_summary: Optional summary of conversation so far
            conversation_history: Optional full conversation history text

        Returns:
            Complete answer as a single string
        """
        return "".join(self(query, conversation_summary, conversation_history))
