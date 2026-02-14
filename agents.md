# AGENTS.md

This file is guidance for agentic coding assistants working in this repo.

## Environment

- Cursor rule: activate conda env with `conda activate science-reader` before running Python.
- Project is primarily Python (Flask backend + agents) with a browser UI in `interface/`.

## Build / Lint / Test Commands

There is no centralized build or lint command configured (no `pyproject.toml`, `setup.cfg`, or `package.json`).
Use the existing test entry points below.

### Core Python Tests (Truth Management System)

- Run all TMS tests:
  - `python -m pytest truth_management_system/tests/ -v`
- Run a single TMS test file:
  - `python -m pytest truth_management_system/tests/test_crud.py -v`
- Run a single TMS test case/test:
  - `python -m pytest truth_management_system/tests/test_crud.py::TestClaimCRUD::test_add_claim -v`

Notes:
- Some integration tests use external keys and may skip if missing.
- `truth_management_system/tests/test_integration.py` also supports a standalone runner
  (see the file for details) to avoid pytest collection issues with numpy/sandbox.

### Prompt Library Tests

- `python -m pytest prompt_lib/test_wrapped_manager.py -v`

### Extension Server Integration Tests

- Recommended auto-start:
  - `cd extension/tests && ./run_tests.sh`
  - or `python extension/tests/run_integration_tests.py`

### Ad hoc files in repo root

- Some standalone tests exist (e.g., `test_slide_agents.py`, `test_serp.py`).
  Run them with `python -m pytest <file> -v` if needed.

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
- Extension server: `python extension_server.py --port 5001 --debug`

## Repo Structure Notes

- Core chat flow: `Conversation.py`, `server.py`, `endpoints/`.
- UI: `interface/interface.html`, `interface/*.js`.
- PKB module: `truth_management_system/`.
- Extension: `extension/` + `extension_server.py`.
- Documentation in markdown files within same module and in documentation folder.
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

### Other guidelines
- Update docs when you add or change behavior. Docs are usually markdown files which are within the same module or within documentation folder.
- When creating or updating documentation, add UI details if applicable, add api details, function details, feature details, add implementation notes and files modified as well so that later we can use this to further enhance the feature.
- Write in markdown format but don't make any diagrams. Our docs are intended to be friendly to LLM agents and software agents, diagrams are not friendly to agents.
- Apply small patches or edits sequentially. Even when writing an entire new file, first touch and create the file and then write in chunks and maybe write outlines and then fill the file if possible.
- Please write in small parts or chunks. Writing very large chunks is error-prone.
