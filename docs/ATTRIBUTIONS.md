# Attributions and artifact provenance

The project owner confirmed that the supplied archive's contents may be made public. This records that authorization; it does not independently establish third-party licenses or replace upstream notices.

| Material | Source/provenance | Distribution note |
| --- | --- | --- |
| Application source, dashboards, icons, logos, and report images | Supplied Project SWING archive | Preserve project attribution and branding. No separate third-party license metadata was included in the archive. |
| IEEE 39/118 network data and derived simulation assets | Supplied project source and artifacts | Research/simulation material; confirm applicable upstream data terms before commercial use. |
| Indian Electricity Grid Code PDF | Central Electricity Regulatory Commission (CERC), India; source file `data/knowledge_base/IEGC_Code.pdf` | Regulatory reference only. It is not an endorsement by CERC. Retain the source PDF's own title and notices. |
| Load/weather datasets and trained weights | Supplied project archive; file-level SHA-256 inventory in `scripts/check_source_manifest.py` | Archive owner authorized public inclusion. Upstream dataset/model licenses and training provenance were not supplied, so commercial-use rights remain unverified. |
| JavaScript libraries | `package-lock.json` | Browser dependencies are locked; see package metadata and each upstream package license. CDN scripts in existing HTML remain external dependencies. |
| Python packages | `requirements.txt`, `requirements-twin.txt` | Each dependency retains its own upstream license; the application license does not relicense dependencies. |

The repository's top-level `LICENSE` applies only as its text states. It must not be read as changing rights in upstream regulatory documents, datasets, or third-party dependencies. Serialized model/index files are not loaded by attribution or audit tooling.
