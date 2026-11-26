"""What the Chat Agent reads about this server: the server's instructions and one description per action
(mcp/server.py)."""

# ---------- server instructions ----------
INSTRUCTIONS = (
    "Refines an assessment rubric until a scoring model's scores agree with the scores people already gave."
    ' Every action takes the chat_id. Files are referred to by the names they were uploaded with'
    ' (list_inputs). Flow: list_inputs -> prepare_run (reads the sheet, finds the metrics, cuts the rubric'
    ' into layers; may come back with questions to answer in the context file) -> run_status until prepared'
    ' -> start_run (runs for a long time in the background) -> get_version_report / get_report when it is'
    ' done. Only the metric sections of the rubric are ever edited; programme context, global notes and'
    ' output format stay word for word.'
    ' A sheet may hold reviewers\' verdicts on an earlier AI run instead of people\'s scores: per metric'
    ' the earlier score, a verdict (agree / too high / too low) and a remark. The refinement treats each'
    ' verdict as a pass/fail check (too high: lower than the earlier score; too low: higher; agree: the'
    ' same) and the remarks as evidence. Never turn a verdict or a remark into a target score, and never'
    ' ask the user for one.'
)

TOOLS = {
    # ---------- list_inputs ----------
    'list_inputs': (
        'The files uploaded to this chat (name and size): the scored sheet, the context notes, the current'
        ' rubric, an\noptional output schema and an optional docs folder.'
    ),

    # ---------- inspect_inputs ----------
    'inspect_inputs': (
        'Look inside every uploaded file: for a table its sheets, columns, row count and first rows; for a'
        ' text,\nmarkdown, JSON or Word file its content; for a PDF its pages and opening text; for a'
        ' folder its files. Use it to\nwork out what each file is (scored sheet, context notes, rubric,'
        ' output format, documents) from its content; file\nnames say nothing reliable.'
    ),

    # ---------- add_context_note ----------
    'add_context_note': (
        "Append the user's answers to the context notes, so the next preparation can use them. context: the"
        ' name of the uploaded context file; leave it out when none was uploaded and the answers start a new'
        ' context.md (pass that name as context when preparing again). note: the answers, written as short'
        ' plain statements.'
    ),

    # ---------- prepare_run ----------
    'prepare_run': (
        'Prepare the run without scoring, in the background: read the sheet, find the metrics and the'
        " reference columns,\ncut the rubric into layers and fetch every submission's attachments. Watch"
        ' run_status: it shows the setup, or\nquestions to answer in the context file (then prepare'
        ' again).\n\nsheet / prompt / schema / context: names of uploaded files; context (the context notes) is'
        ' optional:\nleave it out when none was uploaded. docs_dir: name of an'
        ' uploaded folder of documents for\nlinks that cannot be downloaded. effort: low, medium or high.'
        ' n: use only the first n submissions. split: the train/test share, like 80/20: the rubric is tuned on'
        ' train only and test is scored once at the end, so its numbers are out of sample (100/0 = no holdout);'
        ' seed fixes which submissions go where. n, split and seed are fixed when the run is prepared.'
    ),

    # ---------- start_run ----------
    'start_run': (
        'Start (or resume) the refinement in the background; returns at once. The same files as'
        ' prepare_run. model is\nthe default for every agent; parser_model, judge_model, generator_model'
        ' and scorer override it one by one; scorer is the model production scores with (generative, or a'
        ' decision model: gpt-6-luna-decisions, gemini-decision-1); scorer_effort sets the scoring model alone (default low).'
        ' Stop\nrules: rounds (most rounds per metric), patience'
        ' (rejected rounds in a row), target (stop at this average gap on train), budget (USD: stop at the next'
        ' round once spent, best kept; run_status shows what was spent). split / seed as in prepare_run;'
        ' the values stored at preparation win on a resume.'
    ),

    # ---------- run_status ----------
    'run_status': (
        "Where the run stands: running or not, the setup or the parser's questions, each metric's round,"
        ' best version\nand numbers, the issue checklist, how it stopped, and what it has spent (USD, per model).'
    ),

    # ---------- stop_run ----------
    'stop_run': (
        'Stop the run. Progress is kept; start_run resumes it.'
    ),

    # ---------- get_checklist ----------
    'get_checklist': (
        'The issue checklist (root cause, students, rubric clause, fix, status each round). With several'
        ' metrics, pass\nthe metric key; without it, the run-level checklist.'
    ),

    # ---------- get_version_report ----------
    'get_version_report': (
        'Every version of each metric (or one metric): parent, verdict (baseline / kept / rejected), round,'
        ' numbers\n(average gap, bias, within 1 and 2, exact matches), students moved closer / further, and'
        ' the change summary.'
    ),

    # ---------- get_rubric ----------
    'get_rubric': (
        "One version's metric section and the section it was made from (its parent)."
    ),

    # ---------- get_report ----------
    'get_report': (
        "The final report: meta, before/after numbers per metric, version lineage and every version's"
        ' rubric section.\nAvailable once the run has finished.'
    ),

    # ---------- get_final_prompt ----------
    'get_final_prompt': (
        "The final rubric (the best version, or every metric's best section stitched together)."
    ),
}
