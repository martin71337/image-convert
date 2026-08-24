"""The PySide6 interface.

**This layer never computes a result.** It builds a
:class:`~imgconv.options.ConversionOptions`, hands it to
:func:`imgconv.job.run`, and renders what comes back. Every decision about how a
pixel is written, where a file goes, or what a format can hold lives below this
package and is reached through the same functions a test or a script would call.

The practical consequence is that no bug in the interface can produce a
different conversion than the engine would - only a different request.
"""
