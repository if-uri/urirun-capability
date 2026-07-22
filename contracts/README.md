# Adopted contract fixtures

These descriptors are the durable output of four completed contract-package
experiments. They are bundled here because `urirun-capability` consumes them in
tests, examples, projections, and migration benchmarks. Runtime code must not
depend on sibling workspace checkouts.

| Fixture | Original repository | Source commit |
| --- | --- | --- |
| `capture-click.json` | `if-uri/urirun-contract-capture-click` | `ab3f5e1` |
| `filepair.json` | `if-uri/urirun-contract-filepair` | `a2181c6` |
| `kvstore.json` | `if-uri/urirun-contract-kvstore` | `4a90258` |
| `windowpair.json` | `if-uri/urirun-contract-windowpair` | `042d339` |

The original repositories demonstrated the generator and multi-process
boilerplate. The maintained form is now the descriptor plus the shared
Capability adoption layer.
