# Subjectdesk

Subjectdesk watches folders named after subjects. Add an assignment file to a subject folder and it records a job in a central SQLite database, asks Claude to research it with web search, and places the completed work in a new folder where the assignment was. The original assignment is kept inside that folder.

## Install

```sh
ownbox sync
ownbox install subjectdesk
```

Manual development install:

```sh
git clone https://github.com/BogdanStamenovic/subjectdesk.git
cd subjectdesk
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

An Anthropic API key is required. Pass a key file with `--key-file`, or set `ANTHROPIC_API_KEY`. The key stays on your machine. Anthropic API requests and web search can incur charges. The account must have web search enabled.

## Usage

```sh
subjectdesk init ~/Assignments
mkdir -p ~/Assignments/History ~/Assignments/Biology
subjectdesk watch ~/Assignments --key-file ~/keys/claude.txt
```

In another terminal, add `~/Assignments/History/roman-roads.md`:

```md
---
title: Roman roads and trade
model: sonnet
formats: [docx, pdf, md]
---
Explain how Roman roads affected trade in the second century CE.
Use reliable sources and include a source list.
Target length: about 1,000 words.
```

After completion, the structure is:

```text
Assignments/
  .subjectdesk/
    jobs.sqlite
    rules.txt
  History/
    roman-roads/
      roman-roads.md
      work.docx
      work.pdf
      work.md
```

`watch` scans every second by default. It waits for a file to have the same size and modification time on two scans before queuing it. Up to two assignments run concurrently by default; use `--max-workers N` to change this. Scanning continues while research runs. Keep `watch` running for automatic processing.

| Command | Purpose |
| --- | --- |
| `subjectdesk init PATH` | Create the workspace and central database. |
| `subjectdesk watch PATH` | Watch subject folders and process new files. |
| `subjectdesk once PATH` | Scan immediately, process queued work, then exit. |
| `subjectdesk status PATH` | Show jobs and states. Add `-v` for errors. |
| `subjectdesk retry PATH JOB_ID` | Requeue a failed or interrupted job. |

`watch` and `once` accept `--model haiku|sonnet` and `--key-file PATH`. An assignment's `model` field overrides the default. The default is Haiku. Supported inputs are `.md`, `.txt`, `.docx`, and text-based `.pdf`. Supported outputs are `docx`, `pdf`, `md`, `txt`, and `html`. Output defaults to `docx` when no format is specified. A plain text line such as `Formats: docx, pdf` also works.

## Writing rules

Every job gets the built-in rules plus `.subjectdesk/rules.txt`. The built-in rules require plain, natural writing, no em dashes, no emojis, no character acting, honest uncertainty, and direct source URLs for researched claims. Em dashes and emoji characters are also removed from returned titles and document text before files are written. You can add subject-specific instructions to `rules.txt`.

The assignment is retained in its output folder. A failed job leaves the original assignment in place and records its error in SQLite. Use `status -v` and `retry` after fixing the issue. An interrupted `running` job can also be retried.

On startup, `watch` and `once` automatically requeue jobs interrupted by a previous process. A workspace lock prevents two processing commands from running against the same workspace at once.

## Keep the watcher running

For a user service on a systemd machine, create `~/.config/systemd/user/subjectdesk.service`:

```ini
[Unit]
Description=Process Subjectdesk assignments

[Service]
ExecStart=%h/.local/bin/subjectdesk watch %h/Assignments --key-file %h/keys/claude.txt
Restart=on-failure

[Install]
WantedBy=default.target
```

Then run `systemctl --user enable --now subjectdesk.service`. Adjust the paths to your workspace and key file.

## Limitations

- Research depends on Anthropic's web search tool. Subjectdesk records a failure if the API call fails. It cannot guarantee the truth of model claims, so check important work and sources before submitting it.
- Scanned PDFs need OCR before they can be used as assignments.
- PDF output needs a DejaVu or Liberation Sans TTF font installed locally.
- The watcher does not start automatically after installation. Run it in a terminal or as a user service.
- Editing an assignment after it has been queued does not create a new job. Retry a failed job or add a new assignment file.

The API setup follows Anthropic's [Messages API](https://platform.claude.com/docs/en/api/messages/create) and [web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool) documentation.
