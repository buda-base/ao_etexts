# TEI “Non-Paginated Shape” — Minimal Spec

This supposes the reader is familiar with the [Paginate Shape spec](tei_xml_spec_paginated.md).

## 1) The smallest valid file

The minimal shape is a much simplified version of the paginated shape:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:lang="bo">
        <p>༄༅། །ཆོས་མངོན་པ་མཛོད་ཀྱི་འགྲེལ་པ་མངོན་པའི་རྒྱན་གྱི་དཀར་ཆག་དང་ས་བཅད་གླེང་བརྗོད་བཅས་བཞུགས་སོ༎
༄༅། །ཨོཾ་སྭ་སྟི། །གང་གི་མཚན་ཙམ་ལན་ཅིག་ཐོས་པས་ཀྱང་། །མཚམས་མེད་ལས་ལ་སྤྱོད་པའི་སྡིག་ཅན་ཡང་། །ཕྱི་མ་ངན་འགྲོའི་འཇིགས་ལས་སྐྱོབ་མཛད་
༄༅། །དབྱེ་བ་དང་། མཚན་ཉིད་དང་། དགོས་པ་དང་། གྲངས་ངེས་དང་། གོ་རིམས་ངེས་པ་ལྔ་བཤད་པ།
        </p>
    </body>
  </text>
</TEI>
```

## 2) Structured shape

A structured shape can be encoded in the following way:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:lang="bo">
      <div>
        <head>མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།</head>
        <p>༄༅། མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས། སྒྲུང་བ་རིག་འཛིན་བཟང་པོའམ་ཁྱི་ཤུལ་རིག་བཟང་ནི། རབ་བྱུང་བཅུ་བཞི་པའི་ཤིང་སྦྲུལ་༼༡༨༤༥ ༡༩༤༩༽ལོར་གཡུ་ཁོག་ཏུ་ཁྱི་ཤུལ་ཞེས་པའི་རིགས་སུ་སྐུ་འཁྲུངས། གཡུ་ཁོག་བྱ་བྲལ་ཆོས་དབྱིངས་རང་གྲོལ་དང་སྤུན་མཆེད་ཐོབ་པར་བཤད། མདོ་མཁྱེན་བརྩེ། རྒྱལ་སྲས་གཞན་ཕན་མཐའ་ཡས། གཡུ་ཁོག་རྒྱ་སྤྲུལ་སོགས་ལས་ཟབ་ཆོས་གསན། ཉིན་ཞིག་གཡུའི་ལམ་ཤར་ཁ་རུ་ཕེབས་སྐབས་གླིང་སྤྱི་དཔོན་རོང་ཚ་ཁྲ་རྒན་དང་། འབུམ་པ་རྒྱ་ཚ།</p>
      </div>
    </body>
  </text>
</TEI>
```

where divs can contain other divs.