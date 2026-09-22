---
name: huh
description: Type "huh" (or "huh?") the moment a message from the agent doesn't land. The agent re-pitches what it just said in plain language, using this repo's own terms from docs/VOCABULARY.md instead of jargon. User-invoked only — never fire this on your own initiative.
---

# Huh?

That last message didn't land. Re-pitch it:

- Add the context that was missing. Don't just delete words — restate the point
  with the premise the reader needs to follow it.
- Write in plain language. Short sentences, one idea per sentence, no filler.
- Use this repo's own vocabulary, not invented or borrowed terms. If
  `docs/VOCABULARY.md` exists, pull the project's canonical words from it
  (e.g. molecule, bead, gate, oracle, continuation harness) instead of generic
  synonyms. If it doesn't exist, skip this step — the plain-language repair
  still applies.
- Repair the one message. Don't restart the conversation, don't re-summarize
  everything said so far, and don't apologize at length — just say it better.

This is a one-shot corrective, not a standing instruction. Using it twice in a
row should not make the agent terser each time; it should still add whatever
context was missing the second time too.
