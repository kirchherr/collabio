# Prompt Registry

Prompts must be versioned and reviewed. They must not be scattered through feature code.

## Required fields

- id
- version
- owner
- allowed_data_classes
- required_sources
- output_schema
- known_risks
- test_cases
- approval_status

## MVP prompts

- `document_summary_v1`
- `rag_answer_v1`

Both prompts are represented by the in-memory prompt registry and covered by policy checks.

The default prompts allow `ai_prompt` because the user's question or instruction is itself classified input. RAG prompts must also allow every source data class they are permitted to receive. The pipeline must derive those source classes from authorized source objects, not from the requester's claimed intent.
