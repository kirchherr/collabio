# AI Risk Register

| Risk | Impact | Mitigation | MVP gate |
| --- | --- | --- | --- |
| Prompt injection | Tool misuse or data leakage | Treat retrieved content as untrusted and require tool permissions | Prompt templates separate instructions from sources |
| Vector DB leakage | Unauthorized discovery | Candidate-only vector search plus authoritative ACL check | Tests verify unauthorized sources are filtered |
| Hallucination | Wrong business facts | Source citations and low-confidence labels | RAG responses include source list |
| Sensitive output logging | Data exposure | Hash prompt/output in audit; avoid normal logs | Audit logger stores hashes |
| Excessive agency | Unsafe autonomous action | Human approval for high-risk actions | Risk level maps to approval flag |
| Voice privacy failure | Personal data exposure | Push-to-talk and no raw audio default | Voice endpoint rejects inactive capture |

