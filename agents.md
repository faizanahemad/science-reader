# AGENTS.md

## Environment

- Cursor rule: activate conda env with `conda activate science-reader` before running Python.
- Project is primarily Python (Flask backend + agents) with a browser UI in `interface/`.

## Code Style Guidelines

- Imports: prefer standard library, third-party, then local imports. Avoid reordering imports in legacy files unless you are already editing that import block.
- Avoid reinventing the wheel, wherever possible use libraries. Reusable code is in `code_common/` folder and files named with words like "common", "util", "base", etc.
- Docstrings: Add docstrings for new public functions/classes (purpose, inputs, outputs).
- Logging: loggers are defined at top of file already in most cases and come from `getLoggers` from `loggers.py`.

### Flask / Endpoints

- Use rate limiting decorators where present and consistent with the file.
- Maintain newline-delimited streaming responses where used elsewhere.
- Validate inputs early; return 4xx errors for user errors.

### JavaScript (interface/)

- UI uses jQuery + Bootstrap 4.6. Stick to the existing event handler patterns.
- When adding buttons/menu entries, wire up handlers in the same module.
- Avoid silent failures in new code paths; surface errors to UI with `showToast`.

## Common Entry Points

- Web server: `python server.py`

## Repo Structure Notes

- Core chat flow: `Conversation.py`, `server.py`, `endpoints/` and mentioned in `documentation/features/conversation_flow/conversation_flow.md` and chat app capabilities mentioned in `documentation/product/behavior/chat_app_capabilities.md`.
- UI: `interface/interface.html`, `interface/*.js`.
- PKB module: `truth_management_system/`.
- common LLM calling code at `code_common/call_llm.py`
- Documentation in markdown files in documentation folder with entry point as documentation/README.md.
- Feature documentation in documentation/features
- Planning documents go into documentation/planning/plans and have extension as `.plan.md`.

## Guidance for Agents

### Planning guidelines

- Focus on quality and correctness, we have all the time and compute resources.
- When making or improving a plan, go through more code and details using parallel tools or agent calls. Dive deeper and wider.
- Write down requirements and goals first, then plan the solution, break it into granular tasks and sub-tasks, then write code.
- Plan strategically in logical small steps. Build incrementally so errors in later tasks don't leave earlier work unusable. Note alternatives and possible challenges so the executor has autonomy to make decisions.
- Ask clarification questions on UX, features, implementation, and maintainability.

### Coding guidelines

- Write modular code as functions and separate modules with reusable interfaces, then integrate into existing systems.
- Apply small patches or edits sequentially and write in small chunks — large chunks are error-prone. When writing an entire new file, create the outline first, then fill gradually.

### Documentation guidelines
- View the docs in `documentation` folder by running `tree documentation` bash command. View the docs also when asked for context around a functionality or plan.
- Update docs when you add or change behavior. Docs are markdown files in the documentation folder.
- When creating or updating documentation, add motivation and background, UI details if applicable, API details, function details, feature details, implementation notes and files modified.
- Write in markdown format but don't make diagrams. Our docs are intended to be friendly to LLM agents; diagrams are not.

### Context management and calling sub-agents

- For reading large files (>200 lines): 1. `wc -l filename`, 2. Call a sub-agent to get an outline by grepping for headers and relevant patterns, 3. Read the exact lines needed. If outline parsing doesn't work, call a sub-agent with your query to get relevant info and line numbers.
- If multiple files need to be edited in parallel, use sub-agents. Give the location of the plan or task file for context.
- Your context length is small — delegate surveying, reading large files, or looking up code across multiple files to sub-agents. Return only important and useful parts to prevent context bloat.
- For file tree browsing use `tree` command (if not present use `ls`).
- After context loss from compaction or summarization, use `git status`, `git diff`, and `session_search`/`session_list`/`session_read` tools to recover context.
- Wait patiently for background tasks. Use their results rather than cancelling them.
- Don't delegate documentation or plan writing to sub-agents as they may not have full context. Delegate well-defined code writing, reading, surveying, or search tasks.

### MCP tool usage guidelines (not for coding)

- Global documents can be listed via `docs_list_global_docs` and retrieved by `doc_storage_path` using `docs_get_full_text` or `docs_query`. If only a `doc_id` is given, list global docs first, match by `doc_id`, then use the corresponding `doc_storage_path` to access content. Always get the user email by decoding the JWT: `echo $MCP_JWT_TOKEN | cut -d'.' -f2 | base64 -d 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['email'])"` — never guess or hardcode the email.
