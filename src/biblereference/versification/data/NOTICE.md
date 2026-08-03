# Versification data — attribution

The files `org.json`, `eng.json`, `lxx.json`, `vul.json`, `rsc.json`, and `rso.json` in
this directory are vendored from the Copenhagen Alliance versification specification:

> <https://github.com/Copenhagen-Alliance/versification-specification>
> Copyright © The Copenhagen Alliance for Open Biblical Language Resources.
> Data licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/);
> code in that repository is licensed under Apache 2.0.

Vendored 2026-08-03. `COPENHAGEN-LICENSE.md` is the upstream license file, retained
unmodified as CC BY-SA requires.

**Share-alike scope.** These JSON files, and `corrections.json` (which is an adaptation of
them), are CC BY-SA 4.0. The rest of `biblereference` is MIT and merely reads them at
runtime; it is not a derivative of the data.

**Modifications.** The vendored files are byte-for-byte upstream. Corrections are applied
at load time from `corrections.json` rather than by editing the sources, so that a refresh
from upstream is a clean overwrite and the loader can tell you when a correction has become
unnecessary. Every correction records what was wrong and how the fix was verified.
