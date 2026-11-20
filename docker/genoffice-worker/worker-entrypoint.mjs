const status = {
  engine_execution_allowed: false,
  production_use_allowed: false,
  schema_version: "genoffice_worker_candidate_status.v1",
  source_import_allowed: false,
  tenant_content_allowed: false,
  worker_execution_allowed: false,
};

process.stdout.write(`${JSON.stringify(status)}\n`);
process.exitCode = 78;
