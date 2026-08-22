# Third-party notices

SAMADCON itself is AGPL-3.0-or-later; see [LICENSE](LICENSE). This file covers
material from elsewhere that ships inside it, and the terms that come with it.

It lists what is *embedded in the product*, not what is installed alongside it.
Python and npm dependencies carry their own licences in their own packages and
are not repeated here.

---

## Phosphor Icons

Most of the icons in the console — the six console tabs, and the objects in the
tree and the lists — are Phosphor Icons at regular weight. They are embedded as
SVG path data in `frontend/src/components/primitives.tsx` rather than loaded as
files: the content security policy allows no external sources, and an icon that
arrives over the network is an icon that can fail to arrive.

Source: <https://github.com/phosphor-icons/core>

The one exception is the generic fallback, drawn for this project, used for an
object type that has no icon of its own. It is on a different grid, which is
why each icon carries its own viewBox.

```
MIT License

Copyright (c) 2023 Phosphor Icons

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

MIT is compatible with AGPL-3.0-or-later, and the notice above is reproduced in
full because MIT requires it to travel with every copy — which, for icons
compiled into a bundle, means this file.
