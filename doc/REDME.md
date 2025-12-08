## BDRC Archival Etext Format Documentation

This document describes the conventions used to archive etexts by BDRC.

#### Conceptual model

The etext archive is primarily concerned with:
- long-term preservation of files
- clear and enforced encoding conventions of contents
- clear and enforced folder structure conventions in connection with the BDRC catalog

The concepts it uses are:
- *instance*: a publication (ex: the Peydurma Kangyur). Typically instances have properties like cover page title, publisher name, ISBN, etc.
- *etext instance*: etexts corresponding to an instance (ex: OCR of the Peydurma Kangyur)
- *etext volume*: an etext or set of etexts corresponding to one volume of the the instance (ex: OCR of volume 3 of the Peydurma Kangyur)
- *etext* or *etext unit*: an etext file (ex: OCR of page 23 of volume 3 of the Peydurma Kangyur)

The identifiers typically used are:
- identifiers starting with `MW` for instances (ex: `MW3KG218`)
- identifiers starting with `IE` for etext instances (ex: `IE3KG218`)
- identifiers starting with `VE` for etext volumes (ex: `VE1ER123`)
- identifiers starting with `UT` for etext units (ex: `UT1ALS00415M_0001`)

#### Documentation overview

The folder structure of the archival object for an etext instance is documented in [folder_structure.md](folder_structure.md).

The XML conventions used to encode etext units are documented in:
- [tei_xml_spec_header.md](tei_xml_spec_header.md) for the minimal TEI header
- [tei_xml_spec_paginated.md](tei_xml_spec_paginated.md) for the TEI body of the etexts that have a notion of page