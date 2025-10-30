# TEI “Paginated Shape” — Minimal Spec

**Audience:** non-experts
**Goal:** a very small TEI/XML subset for page-accurate transcriptions of Tibetan works.
**Character set:** Unicode (UTF-8).
**Namespace:** `http://www.tei-c.org/ns/1.0`

---

## 1) The smallest valid file

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
<pb n="1a"/>
<lb/>༄༅། །ཆོས་མངོན་པ་མཛོད་ཀྱི་འགྲེལ་པ་མངོན་པའི་རྒྱན་གྱི་དཀར་ཆག་དང་ས་བཅད་གླེང་བརྗོད་བཅས་བཞུགས་སོ༎
<pb n="1b"/>
<lb/>༄༅། །ཨོཾ་སྭ་སྟི། །གང་གི་མཚན་ཙམ་ལན་ཅིག་ཐོས་པས་ཀྱང་། །མཚམས་མེད་ལས་ལ་སྤྱོད་པའི་སྡིག་ཅན་ཡང་། །ཕྱི་མ་ངན་འགྲོའི་འཇིགས་ལས་སྐྱོབ་མཛད་
<pb n="2a"/>
<lb/>༄༅། །དབྱེ་བ་དང་། མཚན་ཉིད་དང་། དགོས་པ་དང་། གྲངས་ངེས་དང་། གོ་རིམས་ངེས་པ་ལྔ་བཤད་པ།
</p>
    </body>
  </text>
</TEI>
```

**Why `xml:space="preserve"`?**

Because we want to keep all spaces and line starts exactly as typed, which is not the default behavior of XML. Do **not** indent lines or wrap lines inside this `<p>`.

In XML, whitespace that appears between elements or around inline markup is usually non-semantic, so `<a>b</a>c` and `<a>b</a> c` are typically equivalent, which is not ideal if we want to keep a space before `c`. The attribute `xml:space="preserve"` changes that default by explicitly signaling that whitespace must be kept exactly as written, making spaces and newlines significant for processing and rendering.

---

## 2) High-level rules

1. **Structure (fixed skeleton)**

   * `<TEI><text><body><p xml:space="preserve">…</p></body></text></TEI>`
   * Put the whole transcript inside **one** `<p xml:space="preserve">`.
   * Default language: `<body xml:lang="bo">` (Tibetan). Use other `xml:lang` on elements when needed (e.g., English notes).

2. **Pagination and line breaks**

   * **Page/folio break:** `<pb n="1a"/>`, `<pb n="1b"/>`, `<pb n="2a"/>`, etc.

     * `n` is a string you copy from the source (e.g., folio+side). Use **a/b** for recto/verso if applicable.
     * Place `<pb/>` **before** the first line of that page.
   * **Line break:** `<lb/>` before each line’s text on that page.
   * Do **not** put text inside `<pb>` or `<lb>`; they are **empty** elements.

3. **Whitespace**

   * Keep all spaces and line starts (because of `xml:space="preserve"`).
   * Do not add or remove spaces around `<pb/>` and `<lb/>`.

4. **Unicode & punctuation**

   * Use proper Tibetan Unicode characters.
   * If you need XML special characters in notes or captions, escape them:

     * `&` → `&amp;`, `<` → `&lt;`, `>` → `&gt;`.

5. **Namespace**

   * Always include: `xmlns="http://www.tei-c.org/ns/1.0"` on `<TEI>`.

---

## 4) Content annotations (editorial & visual)

These can appear **inside the `<p>`**, between `<lb/>` and text, or wrapping spans of text.

### 4.1 Notes

* Editorial notes (e.g., explanations, glosses).
* Use `xml:lang` for the language of the note.

```xml
<note type="editorial" xml:lang="en">Correction by editor.</note>
```

### 4.2 Figure caption (no image embedding here)

* For captions or titles of illustrations.

```xml
<figure>
  <head xml:lang="bo">རིས་ཀྱི་མཚན་བྱང་།</head>
</figure>
```

### 4.3 Illegible or missing text

* **Completely unreadable:** use `gap` with a reason and units.

  * `unit="syllable"` and `quantity="N"` (estimated syllables).

```xml
<gap reason="illegible" unit="syllable" quantity="1"/>
<!-- or quantity="3" if estimated -->
```

* **Unclear but reconstructable:** wrap what you read/reconstruct in `unclear`.

  * Add `reason="illegible"` and optional `cert="low|medium|high"`.

```xml
<unclear reason="illegible" cert="low">བོད་</unclear>
```

### 4.4 Small-letter (yigchung)

```xml
<hi rend="small">ཡིག་ཆུང་།</hi>
```

### 4.5 Editorial emendations

Use a `choice` to show original vs corrected reading.

```xml
<choice>
  <orig>བླ་མ་</orig>
  <corr cert="low">བླ་མ།</corr>
</choice>
```

* `cert` on `<corr>` is optional; use when uncertain.

### 4.6 Modern styling (from modern sources)

* Italic: `<hi type="italic">…</hi>`
* Bold: `<hi type="bold">…</hi>`
* Headings: `<hi type="head">…</hi>` or levels: `head_1`, `head_2`, …

```xml
<hi type="italic">བོད་</hi>
<hi type="bold">ཡིག</hi>
<hi type="head">Section Title</hi>
<hi type="head_1">Main Title</hi>
```

---

## 5) Element placement patterns

**Typical line with annotations**

```xml
<lb/>…normal text… <unclear reason="illegible">མཚན</unclear> … <note type="editorial" xml:lang="en">Place name</note>
```

**Line with a lacuna**

```xml
<lb/>…text… <gap reason="illegible" unit="syllable" quantity="2"/> …text…
```

**Page change mid-paragraph**

```xml
<lb/>…end of page text…
<pb n="12b"/>
<lb/>…start of next page…
```

**Caption separated from running text**

```xml
<lb/>…text referring to a figure…
<figure><head xml:lang="bo">རིས་ཀྱི་མཚན་</head></figure>
<lb/>…text continues…
```
