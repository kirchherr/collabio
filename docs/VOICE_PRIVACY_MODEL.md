# Voice Privacy Model

## Defaults

- Push-to-talk is the default activation model.
- Always-on microphone capture is forbidden by default.
- Raw audio is not stored unless tenant policy explicitly permits it.
- Transcripts are personal data and receive a retention policy.
- Voice commands cannot bypass permission checks.

## MVP behavior

- The API accepts transcripts only when explicit activation is present.
- Raw audio storage requests are rejected unless tenant policy allows them.
- Accepted transcripts are audit logged by hash, not by plain text in normal logs.

## Out of scope for MVP

- Emotion detection
- Voice biometric identification
- Always-on assistant behavior

