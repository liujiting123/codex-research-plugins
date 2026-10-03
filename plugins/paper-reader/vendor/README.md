# PDF.js

Bundled PDF.js 5.6.205 from [mozilla/pdf.js](https://github.com/mozilla/pdf.js), distributed under the [Apache License 2.0](PDFJS-LICENSE).

The browser bundles retain their original code and license headers. Their final ESM export statements were removed so the self-contained reader can use the existing `pdfjsLib` and `pdfjsWorker` globals in its sandboxed document. The reader uses PDF.js's main-thread worker to avoid relying on external URLs or iframe worker permissions.
