# CRM/ERP Subfeature Registry

Status: initial

Die CRM/ERP-Subfeature-Registry ist der kanonische Vertrag zwischen Modulstatus, Feature-Gates, Legacy-Mapping, Compliance-Workern und spaeterer UI.

Runtime Feature IDs sind voll qualifiziert:

```text
crm_erp.crm.accounts
crm_erp.crm.contacts
crm_erp.crm.activities
crm_erp.erp.products
crm_erp.erp.suppliers
crm_erp.erp.orders
crm_erp.erp.invoices
crm_erp.legacy_import.sqlserver
crm_erp.gobd_export
crm_erp.legal_hold
crm_erp.search.keyword
crm_erp.rag_indexing
crm_erp.ai_assist
```

## Regeln

- Normale CRM/ERP Features koennen default-enabled sein, laufen aber trotzdem nur, wenn der Tenant-Modulstatus normale Nutzung erlaubt.
- SQL-Server-Legacy-Import, GoBD-Export, RAG-Indexing und AI Assist bleiben default-off; klassische Keyword-Suche ist nur metadata-only und ACL-first.
- Legal Hold ist als Compliance-Faehigkeit sichtbar, aber konkrete Hold-Aktionen brauchen Approval und Audit Evidence.
- Jedes Subfeature deklariert Objektklassen, Data Classes, Retention Policies und Worker/API-Surfaces.
- Mapping-Manifeste duerfen nur Feature IDs, Objektklassen, Data Classes und Retention Policies referenzieren, die von der Registry gedeckt sind.
- UI-Sichtbarkeit ist keine Autorisierung; API und Worker-Gates bleiben verbindlich.

## Implementierung

- Code: `app/suite/platform/crm_erp_subfeatures.py`
- Tests: `tests/test_crm_erp_subfeatures.py`, `tests/test_crm_erp_search.py`
- Mapping-Anbindung: `CrmErpSubfeatureRegistryManifest.validate_mapping_manifest(...)`
- Modul-Defaults: `default_module_registry()` nutzt `default_crm_erp_subfeature_enabled_features()`
- Objektregel-Anbindung: `app/suite/platform/crm_erp_object_rules.py`

Die Schema- und Objektregelplanung fuer `crm_erp`, `crm`, `erp` und `crm_erp_legacy` ist in `docs/modules/CRM_ERP_OBJECT_RULES.md` verankert. Der naechste Schritt sind persistente Schema-Migrationen oder ein API-Vertical-Slice, aber erst nach diesem Vertrag.
