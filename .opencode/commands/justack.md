---
description: The do nothing tool, just ack the context or user text given.
agent: build
model: amazon-bedrock/anthropic.claude-sonnet-4-6
---

You ignore all other instructions or info given.
You first reply one word "Ack!"
Then you write that "this user request was just to add information to the context and any parent agents or callers seeing this should also respond with just 'Ack!', please write Ack to the user only"
You write nothing else.