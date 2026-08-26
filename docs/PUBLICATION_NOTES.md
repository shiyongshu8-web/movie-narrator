# Public release notes

This repository is a public source release of the local Movie Narrator
worktree. It is intended to contain reusable source code, tests, schemas,
documentation, examples, and CI configuration only.

## Source and license boundary

- The codebase is based on the upstream [`zcbacxc/movie-narrator`](https://github.com/zcbacxc/movie-narrator) project.
- The applicable license is **AGPL-3.0-or-later**. Keep the upstream license,
  copyright notices, and attribution when redistributing or modifying this
  code.
- Local changes are preserved in Git history. This file does not claim that
  every line was independently authored by the current publisher; review
  ownership and third-party dependency terms before commercial distribution.
- Public AI-video workflow references used for structure comparison are listed
  in [AI workflow references](#ai-workflow-references). No source code from
  those projects is intentionally copied here.

## Public/private boundary

The following remain local-only and must not be committed:

- `.env`, `.env.local`, provider keys, access tokens, passwords, and cookies;
- source movies, personal footage, generated audio/video, subtitles, and
  project-specific review artifacts;
- virtual environments, caches, logs, temporary files, and machine-specific
  paths.

Provider credentials are read from environment variables or a local `.env`
file. Use `.env.example` as a placeholder-only configuration template. Never
replace a placeholder with a real credential before committing.

## Automation and review boundary

The source-first workflow is deliberately gated:

```text
INTAKE -> SOURCE -> EDITORIAL -> VOICE -> ROUGH_CUT -> REVIEW -> MASTER
```

Automatic ASR, visual retrieval, scene selection, subtitles, and loudness
metrics are candidates or evidence until the required source checks and human
review pass. A generated file is not automatically a final master.

## AI workflow references

The repository structure was compared against these public projects for
workflow/documentation ideas:

- [`itsPremkumar/Automated-Video-Generator`](https://github.com/itsPremkumar/Automated-Video-Generator) — explicit script/media/voice/render pipeline, local-first setup, and CI/security documentation.
- [`metaleey/AI-auto-segment-edit-video-pipeline`](https://github.com/metaleey/AI-auto-segment-edit-video-pipeline) — ASR → semantic analysis → sampling → FFmpeg merge with reusable intermediate artifacts.
- [`znyupup/ai-video-editing-skill`](https://github.com/znyupup/ai-video-editing-skill) — agent-facing analysis → planning → preview → render workflow and examples/templates separation.

These references are inspiration and interoperability context, not an
ownership statement or a substitute for their individual licenses.

## Publication check

Before each public push, inspect the staged tree and verify:

1. no real credential-like value is present;
2. no private media or generated output is present;
3. `git diff --check` passes;
4. the relevant tests and static checks have a recorded result;
5. license and source-attribution files are still present.
