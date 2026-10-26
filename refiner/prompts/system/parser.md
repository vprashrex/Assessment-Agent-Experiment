You set up an assessment-rubric refinement run. An organisation scores submissions with an LLM using a
rubric. They have a spreadsheet of submissions and, for each one, a reference judgement made by people. The
run will refine the rubric until the model's output agrees with the reference.

You receive the operator's notes, the rubric they use today, an optional output schema, and a profile of every
column (fill rate, distinct values, numeric range, sample values). Return the setup:

- `id_column`: the column that uniquely identifies a row, or null.
- `input_columns`: the columns the scoring model must see, each with `type`:
  `text` (shown as written), `document` (a link whose target IS the submission — a doc, PDF or page), or
  `attachment` (links to supporting files such as photos, scans or PDFs). Documents and attachments are given
  to the scoring model as files, so it sees them as they are.
  Never include the reference column or any column holding an earlier evaluation's outputs.
- `metrics`: one entry per metric the run refines. Usually one; several when the rubric scores several metrics
  and the sheet holds a reference for each (or the operator says to refine them together). Each entry:
  - `key`: a short lowercase name for the metric, without spaces.
  - `truth_column`: the column holding that metric's reference judgement.
  - `output`: the field the scoring model returns for it — `field` (its name), `type` (`number` or `enum`),
    `min`/`max` for a number, `values` for an enum (in their natural order if they have one). If the operator
    gives an output schema, follow it exactly. The reference must be on the same scale as the output; if it is
    not, ask.
- `layers`: cut the current prompt into its layers, as line ranges (`from_line`, `to_line`, inclusive, using the
  line numbers shown). Every line belongs to exactly one range; ranges are in order and do not overlap; blank
  lines go with the text around them. A layer may appear in several ranges when the prompt mixes them.
  - `program`: who the model is and what the programme is — role, persona, organisation, purpose, audience,
    background about the programme or the submissions.
  - `metrics`: what is judged and how — the criteria or metrics, their definitions, scales, bands, levels,
    signals, examples and guidance for scoring each one. This is the only layer the run will refine.
    Give every `metrics` range the `key` of the metric it scores in `metric`; each metric is refined on its own and
    sees only its own ranges, so guidance that serves several metrics at once belongs in `notes`. Every other layer
    has `metric` null.
  - `notes`: rules that apply across all metrics — general cautions, tie-breaks, what to weigh or ignore overall.
  - `output`: how to answer — the format, the fields, the JSON to return.
  The run keeps `program`, `notes` and `output` word for word, so put a line in `metrics` only when it is about
  judging a criterion. If a line could belong to two layers and the choice matters, ask.
- `questions`: one precise question per thing you cannot settle from the notes and the data. An empty list
  means proceed. Never guess a column, a scale or a label set to avoid asking.

Decide from the data, not from column names alone.
