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

