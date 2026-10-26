# utils/ — helpers with no refiner logic

Nothing here knows about rubrics, metrics or runs; each file would work the same in another project.

| File | What it does |
|---|---|
| `excel.py` | spreadsheets: `read_sheet` (xlsx or csv, hyperlinks resolved, empty rows and columns dropped), `write` (a workbook from named row lists), and the row builders for `results.xlsx` and `versions/vN/result.xlsx` |
| `documents.py` | text out of files: `docx` (text and embedded images), `html_text` (a page's readable text), `extension` (a downloaded file's type from its first bytes) |
| `downloads.py` | `fetch(url)`: a linked file downloaded once into `cache/files/` (Google Docs as PDF, Drive files, any URL), else a matching file from the docs folder |
| `files.py` | `read(path, default)`: a JSON or text file; `last_json_line(path)`: the last complete line of a JSONL file |
| `process.py` | `alive(pid)` (not a zombie), `reap(pid)` |

Rule: helpers may import `refiner.paths` for the project folder, nothing else from the refiner.
