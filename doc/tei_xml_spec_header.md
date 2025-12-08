## The TEI header structure

The TEI header used in BDRC archive files is extremely small as the bibliographical information is maintained in BDRC's bibliographical database and not duplicated in the xml files. An example of a valid file is:

```xml
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>སེང་ཆེན་ནོར་བུ་དགྲ་འདུལ་གྱི་སྐུ་ཚེའི་སྟོད་ཀྱི་རྣམ་ཐར་ཉི་མའི་དཀྱིལ་འཁོར་སྐལ་ལྡན་ཡིད་ཀྱི་མུན་སེལ།</title>
      </titleStmt>
      <publicationStmt>
        <p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
      </publicationStmt>
      <sourceDesc>
        <bibl>
          <idno type="src_path">VE3KG215/GSP001.txt</idno>
          <idno type="src_sha256">1f7af4ed852b03e923245edc2313f41fe2e3e9834b5a8cdd51a42d1b52fa4325</idno>
          <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE3KG449</idno>
          <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE3KG215</idno>
          <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT3KG215_0001</idno>
        </bibl>
      </sourceDesc>
    </fileDesc>
    <encodingDesc>
      <p>
        The TEI header does not contain any bibliographical data. It is instead accessible through the 
        <ref target="http://purl.bdrc.io/resource/IE3KG449">record in the BDRC database</ref>
        .
      </p>
    </encodingDesc>
  </teiHeader>
```

The `encodingDesc` and `publicationStmt` can remain exactly as in the example. 

The `bdrc_ie`, `bdrc_ve` and `bdrc_ut` should be set respectively to the `{ie_id}`, `{ve_id}` and `{ut_id}`, prefixed with `http://purl.bdrc.io/resource/`.

The `title` should be set to a proper title for the etext unit, or to the `{ut_id}`.

The `src_path` is mandatory and is the path to the source file that was transformed into the xml file, relative to the `sources/` folder. The `src_sha256` is the sha256 checksum of the source file.