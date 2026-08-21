"""Administrative templates.

An ADMX file describes *what settings exist* and how each maps onto registry
values; the matching ADML file, one per language, carries the text a human
reads. Neither contains any settings — those live in a GPO's ``Registry.pol``.

The split matters for how this package is arranged:

* :mod:`~samadcon.gpo.admx.model` and :mod:`~samadcon.gpo.admx.parser` turn the
  files into a catalogue of definitions. That is pure parsing, with no
  directory and no share involved, and it is where most of the tests are.
* :mod:`~samadcon.gpo.admx.store` fetches the files from SYSVOL and caches them.
* The mapping from a policy's state to registry values is the third piece,
  and the one that decides whether an edit does anything at all.
"""
