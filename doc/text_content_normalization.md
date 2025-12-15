## Unicode text normalization

The text must be normalized in the following way:
- non-Tibetan should be encoded in NFC (normalized form C)
- Tibetan should be normalized according to the rules of the pybo normalizer
- spaces normalization:
   * no spaces at the beginning or end of lines
   * no empty lines
   * no BOM
   * all spaces should be ASCII space (no tabs)
   * no consecutive spaces

All these steps are covered in [botok.utils.corpus_normalization.normalize_corpus()](https://github.com/OpenPecha/Botok/blob/master/botok/utils/corpus_normalization.py#L73)

For more on Tibetan Unicode normalization see [this blog post](https://buda-base.github.io/blog/posts/tibetan-unicode-normalization/)