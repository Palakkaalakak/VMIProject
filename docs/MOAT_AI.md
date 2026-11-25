# Moat AI (built-in local model)

An optional second opinion on a company's moat, on the moat page ("Ask the local AI"). It runs a local model on this PC, researches the
company on the web, applies Adam Khoo's moat framework to the next 10-20 years, cites a source for every claim and reviews its own
verdict. It is never saved and never a verdict: a prompt to check.

## Set-up
1. Settings > AI helper > "Download the built-in AI" (about 7.5 GB: llama.cpp + **Gemma 4 12B**, Google's own 4-bit build, Apache 2.0).
   GPU memory is used first, the rest spills into normal RAM automatically (`vmi/ai_runtime.py`, `gpu_layers()`; override with
   `VMI_AI_GPU_LAYERS`).
2. Web search: put `VMI_TAVILY_API_KEY=tvly-...` in `.env` (free key at tavily.com, 1,000 searches a month, no card). Without a key it falls
   back to DuckDuckGo and Bing, which block heavy automated use. `.env` is git-ignored.
3. Optional, for the **deep** level: `python tools/make_adam_moat.py path/to/VMI_VERBATIM_MASTER_DOCUMENT.md` writes
   `vmi/data/adam_moat.md` (Adam's own words, verbatim). It is the owner's copy of paid course material and is git-ignored.

Only the search words go to Tavily / DuckDuckGo / Bing and the pages it reads are public; nothing else leaves the PC.

## What happens on a run (`vmi/ai_research.py`, `vmi/ai_pipeline.py`)
1. **Research (code-driven).** Short searchable questions (competitors and share, pricing power, switching costs / network effect / barriers,
   threats and the cause of weak numbers, latest results, industry leader). The code searches, ranks sources (company and SEC first),
   opens the best pages (trafilatura), always adds the company's latest 10-K / 20-F competition and risk sections and this app's own
   figures, and the model writes findings with their URLs (UNKNOWN when the pages do not say).
2. **Verdict.** Adam's framework + a 14-item nuance checklist: five sources scored 0-10, claims with sources, grade.
3. **Final pass (always).** The model re-verifies every checklist item itself and may fix the grade (a change needs a sourced reason).
   The lower of verdict and final pass wins; no readable grade counts as NONE.
4. **Checker (optional, tick the box or press the button).** A separate pass answers the checklist on its own first, compares, and its
   grade replaces the opinion's (it can raise or lower).

## Depth levels (the "Depth" dropdown)
| level | framework prompt | research | use |
|---|---|---|---|
| quick (default) | condensed, ~1.6k tokens | 4 questions, 2 pages each | fast |
| standard | + fuller course nuances, ~3.4k tokens | 6 questions (model plans extras), 3 pages, 2 follow-ups | everyday |
| deep | Adam's own words, ~8.6k tokens | 6 questions, 3 pages, 3 follow-ups | important decisions |

## Rules that matter (see the prompts in `ai_research.py`)
- A moat is about the next 10-20 years; "wide today" means nothing. Grading too high is the worst error; lower only for sourced negatives
  from credible sources. Missing information is never a negative.
- "Intense competition" in a 10-K is boilerplate. Weigh each rival by overlap, focus and evidence; competition the company keeps winning is
  not a weakness. Classify each discount (keep customers / win customers / clear stock). Never use the app's automatic pricing-power flag.
- Owner's guidance is labelled separately from Adam's words in the prompt.

## Benchmark (2026-11-20, `tests/fixtures/adam_moat_table.tsv` = Adam's portfolio table)
Gemma 4 12B beat Qwen3-14B and gpt-oss-20b on over-calls (the error that matters). With real web research, the six top names (META, AMZN,
MSFT, AAPL, NVDA, SPGI) and TMO, PANW, FTNT, KO, MCD, WMT came out wide; the remaining misses are borderline (NKE, BABA under; PYPL over).
Single runs flip on borderline stocks, so treat one grade as a prompt to check. Benchmark scripts were throw-away (scratch); the unit tests
(`tests/test_ai_research.py`, `tests/test_ai_pipeline.py`) cover grading rules, levels and the research loop offline.

## Known limits
- Web search quality decides a lot: with empty research the AI falls back to the 10-K alone.
- Idle shutdown of the model server after 10 minutes was not re-verified after the Gemma switch.
- The checker was only exercised in a few runs.

## Explain this company (Analysis page)
A separate, optional read (not a grade): `vmi/ai_explain.py`. Press "Explain this company" on the Analysis page (built-in AI must be ready).
It researches the business, industry, history, management and risks, and explains WHY each metric group is what it is, handing the model the
app's own numbers. Quick = 2 pages per question, deep = 3 and longer sections. Cached 3 days (tick "ignore the cache" to refresh). Every
factual claim should carry a source link; otherwise it says "not found in the sources". Not advice, not saved.
