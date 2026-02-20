# AGENTS.md

This file is guidance for agentic coding assistants working in this repo.

## Environment

- Cursor rule: activate conda env with `conda activate science-reader` before running Python.
- Project is primarily Python (Flask backend + agents) with a browser UI in `interface/`.

## Code Style Guidelines

Follow existing patterns in the file you touch. Do not reformat unrelated code.

### Python

- Indentation: 4 spaces. Keep line length consistent with the surrounding file.
- Imports: prefer standard library, third-party, then local imports. Avoid reordering
  imports in legacy files unless you are already editing that import block.
- Types: type hints are used in newer modules (e.g., endpoints). Preserve and add
  hints where reasonable, especially for public helpers and endpoint handlers.
- Docstrings: many helpers use NumPy-style docstrings. Add docstrings for new
  public functions/classes (purpose, inputs, outputs).
- Errors: prefer explicit exceptions and meaningful messages. In Flask endpoints,
  use `json_error(...)` and `logger.exception(...)` for failures.
- Logging: use `logger` from the module (many files use `logging.getLogger(__name__)`).
- Filesystem access: use existing helpers and ensure directories exist before writes.


### Flask / Endpoints

- Keep endpoints small and delegate logic to helpers or model methods.
- Use rate limiting decorators where present and consistent with the file.
- Check for required payload fields and return structured errors.
- Maintain newline-delimited streaming responses where used elsewhere.

### JavaScript (interface/)

- UI uses jQuery + Bootstrap 4.6. Stick to the existing event handler patterns.
- Prefer `var` in legacy modules to match existing style (unless the file already
  uses `let`/`const` consistently).
- Keep DOM selectors scoped and avoid global side effects.
- When adding buttons/menu entries, wire up handlers in the same module.

### HTML/CSS (interface/)

- Follow existing modal/layout structure. Do not introduce new frameworks.
- Keep CSS near related markup if that is the current pattern.

## Naming Conventions

- Python: `snake_case` for functions/variables, `CamelCase` for classes,
  `UPPER_SNAKE_CASE` for constants.
- JS: camelCase for functions/variables, PascalCase for module-level objects
  when already used (e.g., `ConversationManager`).

## Error Handling and Validation

- Validate inputs early; return 4xx errors for user errors.
- Use `try/except` with `logger.exception(...)` when failures need diagnosis.
- Avoid silent failures in new code paths; surface errors to UI with `showToast`.

## Common Entry Points

- Web server: `python server.py`

## Repo Structure Notes

- Core chat flow: `Conversation.py`, `server.py`, `endpoints/`.
- UI: `interface/interface.html`, `interface/*.js`.
- PKB module: `truth_management_system/`.
- Extension: `extension/` (connects to `server.py` on port 5000). Legacy `extension_server.py` is deprecated.
- Documentation in markdown files within same module and in documentation folder with entry point as documentation/README.md.
- Feature documentation in documentation/features
- Planning documents go into documentation/planning/plans and have extension as `.plan.md`.

## Guidance for Agents
### Planning guidelines
- When making a plan or task list, make it more correct by going through more code and details using parallel tools or agent calls.
- When improving or enhancing a plan, please add more details and corrections to the plam by diving deeper and wider into the code by using multiple parallel agents or tools or LLMs. We got all the money and time in the world.
- First write down the requirements, describe clearly what are the goals and what we are trying to achieve, what has been asked to do and then think carefully how you will solve it and also write down your plan of solution and break it into tasks and sub-tasks which are granular. Then finally write down code. 
- Plan strategically, break it into logical small steps, make multiple tasks, and build in an incremental way such that errors or logical mistakes in later tasks don't leave earlier task work unusable. Also note down alternatives and possible challenges that might be revealed while reading the code more deeply so anyone using the plan will be able to carefully execute it while still having autonomy to make decisions for any risks.
- Plans should have granular milestones and atomic tasks for ease of correctly implementing by a junior dev.

### Coding guidelines
- Work hard, read code, read files and code mentioned in chat, and read documentation and indexes and plans as needed, but basically hard work beats shortcuts, so read more.
- Keep changes minimal and scoped; avoid reformatting large legacy files.
- When writing code, write modular code as functions and separate modules and then integrate into existing systems.
- If you are making corrections or changes to code then first mention what was wrong before and why, then mention what changes or corrections you will make, then finally write corrected code. 
- Ensure to write docstrings for functions and classes describing what they do, inputs, outputs and also their overall purpose and why we created them (if known).
- Make sure to re-use existing code and solutions where ever possible. Reusable code is in files named commonly with words like "common", "util", "base", etc. 

### Context Management and Calling Sub agents
- For reading large readme, code file (python or js and other languages) or markdown files proceed in 3 steps - 1. `wc -l filename`, if file longer than 50 lines then 2. Call a sub-agent asking it to get an outline structure of the file by grepping for headers (`#`, `##`, `####`, `#####`) and other relevant markdown patterns then 3. Read the exact lines. In case outline parsing with sub-agent/LLM doesn't work then try calling a sub-agent or LLM with your query and ask it to give you outline of the document along with information from the doc about your query and tentative line numbers where you can look at.
- If multiple files need to be edited and can be done parallely then use sub-agents to edit the code or other files in a parallel manner.
- Your context length is small, as such delegate tasks like surveying or reading large files or looking up code in multiple files to get answers to sub-tasks or sub-agents. From the delegated tasks or agents return only important and useful parts to the main agent or context to prevent context bloat.
- Breaking tasks and goals into smaller parts, asking sub-agents by delegation to complete them and then the main agent only looking at relevant parts (like api detail or function signature instead of all code, or just survey or grep results or just exact code needed to be read) will help us work faster and save context.
- Spinning up sub-agents and delegation is cheaper than doing it yourself.



### Other guidelines
- Update docs when you add or change behavior. Docs are usually markdown files which are within the same module or within documentation folder.
- When creating or updating documentation, add UI details if applicable, add api details, function details, feature details, add implementation notes and files modified as well so that later we can use this to further enhance the feature.
- Write in markdown format but don't make any diagrams. Our docs are intended to be friendly to LLM agents and software agents, diagrams are not friendly to agents.
- Keep previously added comments and documentation, if they are incorrect then edit and correct them.
- Apply small patches or edits sequentially. When writing an entire new file, first touch and create the file, then put the outline, then write in chunks and then fill the file gradually.
- Please write in small parts or chunks. Writing very large chunks is error-prone.
- Use git status and git diff on tracked files to help know what has changed in repo after you have lost context due to summarization or compaction.
- For file tree browsing and knowing what files exist you can use `tree` command.
- For reading large readme, code file (python or js and other languages) or markdown files proceed in 3 steps - 1. `wc -l filename`, if file longer than 50 lines then 2. Call a sub-agent asking it to get an outline structure of the file by grepping for headers (`#`, `##`, `####`, `#####`) and other relevant markdown patterns then 3. Read the exact lines. In case outline parsing with sub-agent/LLM doesn't work then try calling a sub-agent or LLM with your query and ask it to give you outline of the document along with information from the doc about your query and tentative line numbers where you can look at.
- If files already exist, use edit tool and edit the file. Small edits is better then delete and rewrite. Write in smaller chunks.
- If multiple files need to be edited and can be done parallely then use sub-agents to edit the code or other files in a parallel manner.
- Your context length is small, as such delegate tasks like surveying or reading large files or looking up code in multiple files to get answers. From the delegated tasks or agents return only important and useful parts to the main agent or context to prevent context bloat.
- We have a lot of time and resources at our hand. Wait patiently for background tasks as well. We should use the results of background tasks rather than cancelling them.
