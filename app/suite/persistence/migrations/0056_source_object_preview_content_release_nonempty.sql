-- 0056_source_object_preview_content_release_nonempty.sql
-- Keep sanitized preview release evidence bound to a non-empty released representation.

ALTER TABLE collabio.source_object_preview_content_release_receipts
    ADD CONSTRAINT source_object_preview_content_release_nonempty_output
    CHECK (sanitized_content_byte_length > 0);
