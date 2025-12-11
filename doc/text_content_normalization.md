## Unicode text normalization

The text must be normalized in the following way:
- non-Tibetan should be encoded in NFC (normalized form C), possibly using [this function](https://github.com/buda-base/tibetan-etext-tools/blob/main/DKCC/normalization.py#L76)
- Tibetan should be normalized according to the rules of the pybo normalizer, possibly use [this function](https://github.com/buda-base/tibetan-etext-tools/blob/main/DKCC/normalization.py#L229)
- spaces normalization:
   * no spaces at the beginning or end of lines
   * no empty lines
   * no BOM
   * all spaces should be ASCII space (no tabs)
   * no consecutive spaces
   * possibly use [this function](https://github.com/buda-base/tibetan-etext-tools/blob/main/DKCC/normalization.py#L31)


For more on Tibetan Unicode normalization see [this blog post](https://buda-base.github.io/blog/posts/tibetan-unicode-normalization/)