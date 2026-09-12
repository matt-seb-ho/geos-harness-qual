# GEOS

GEOS is an open-source multiphysics simulator. Tasks require authoring an XML
input deck (or a small set of XML files cross-referenced with `<Included>`).

- A filtered copy of the GEOS repository is mounted read-only at `/geos_lib/`.
  It holds example decks under `/geos_lib/inputFiles/`, the documentation under
  `/geos_lib/docs/`, and the XML schema at `/geos_lib/schema/schema.xsd`.
- Write your final XML deck to `/workspace/inputs/`.
