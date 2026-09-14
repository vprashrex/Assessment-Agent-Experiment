# Operator context (edit freely — the Parser reads this file)

## What the submissions are
Student innovation ideas from the School Innovation Marathon (India, grades 6–12). Each row is one
submission: a title, a problem statement, a solution description, optional attachments (photos of
prototypes, hand-drawn diagrams, handwritten notes, PDFs) shared as Google Drive links, and the
language the student wrote in (English, Hindi, Tamil, Malayalam, Telugu, Kannada).

## Sheet
File: test_ideas.xlsx, sheet `1000_Ideas`.
Use only these columns: `CID` (id), `Title`, `Problem`, `Solution`, `Documents Link` (attachments),
`Language`, `Theme`.
Ignore: `State`, `District`, `DOC type`, `Video Link` (videos are not evaluated), and any empty or
unnamed columns.

## How each submission must be evaluated
The scoring model receives: title, problem, solution, and a neutral text description of each
attachment. It returns five scores (1–10, integers) with a one-line reason each, plus mentor feedback,
exactly in the shape of score_schema.md.

Metrics and what they mean:
- Novelty — how original the problem framing and solution are; textbook/kit/copied ideas score low
  unless the student shows a meaningful adaptation.
- Usefulness — how well the solution actually solves the stated problem for the intended users.
- Feasibility — whether a school student could realistically build/run it with accessible means.
- Scalability — how far it can expand beyond the starting context.
- Sustainability — whether it can last without exhausting resources or harming the environment.

Attachments are supporting evidence: they raise confidence, and change scores only when they add
new design or working clarity that the text lacks. Irrelevant attachments are ignored. Nothing is
assumed that is not stated or visible. Feedback must be in the student's language.

## Initial rubric
prompt.md is the current production rubric (v0). It is the starting point; the agent revises it.
Known issue: scores pile up at 6 and the top of the scale is never used.
