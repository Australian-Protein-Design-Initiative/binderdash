// Render ```mermaid fences, which pymdownx.superfences emits as <div class="mermaid">.
import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';

mermaid.initialize({ startOnLoad: false, theme: 'default' });
await mermaid.run({ querySelector: '.mermaid' });
