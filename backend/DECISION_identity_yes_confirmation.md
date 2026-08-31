# Decision needed: bare "yes" during identity confirmation

## The problem

On a test call:

```
Bot: Am I speaking with Alex?
Me:  Yes.
Bot: I need to speak with Alex, please confirm if you're Alex.
Me:  Yes.
Bot: (politely ends the call)
```

A plain "yes" is never accepted as identity confirmation, even on the second try. The caller has to say something more specific, like "yes, this is me" or "yes, this is Alex," or it gives up and hangs up.

## Why this happens

The identity bot has two buckets for how it classifies an answer:
- **Confirmed** — needs a fuller phrase: "yes this is me," "this is Alex," "speaking," etc.
- **Unclear** — includes plain "yes," "yeah," "yep" on their own.

This was done on purpose. In the past, a plain "yes" caused the bot to wrongly confirm the wrong person at the wrong moment (someone answering the phone with a reflexive "yes?" got treated as the patient confirming their identity). Putting bare "yes" in the "unclear" bucket fixed that. But it also means bare "yes" never counts as confirmation — not even on the retry, after Cara has already asked a very direct, specific question.

## Why we can't just add "yes" back to "Confirmed"

Two ways to do it, both break something:

1. **Add "yes" to Confirmed, but leave it in Unclear too.** Now the same word is a training example for two different answers at once. The bot's behavior in that situation isn't reliable — it's not a real fix.
2. **Move "yes" out of Unclear and only into Confirmed.** This brings back the original bug: on the very *first*, open-ended question ("May I speak with Alex?"), a reflexive "yes?" from whoever picks up the phone would now wrongly confirm them as the patient.

So the fix has to be smarter than a one-line wording change — it needs the bot to treat "yes" differently on the **retry** than on the **opening** question.

## Two ways to actually fix it

### Option A — Give the retry question its own small, separate bot
Right now, the *same* bot handles both the opening question and the retry. Instead, the retry question gets handed to a second, dedicated bot that only ever runs at that one specific moment. In that narrow spot, "yes" is unambiguous, so it can safely mean "confirmed."

This mirrors something already done elsewhere in this project (the "is the patient available" check is already its own separate bot, for the exact same reason — a bare "yes" means something different there too).

- **Pros:** Easy to reason about, matches an already-proven pattern in this codebase, low risk of surprising behavior.
- **Cons:** One more small bot resource to deploy and maintain.

### Option B — Give the main bot a one-turn memory ("context")
The same single bot is used, but it's taught to remember, just for one turn, "I just asked a direct yes/no question." A bare "yes" only counts as confirmation while that memory is active (i.e., only immediately after the retry question) — everywhere else, "yes" behaves exactly as it does today.

- **Pros:** No new bot resource.
- **Cons:** Uses a bot feature ("contexts") this project hasn't used anywhere else before — a bit more of a new pattern to trust and debug if something behaves unexpectedly.

## What needs deciding

Which option to go with — A (separate small bot, proven pattern) or B (one bot, new "memory" feature). Either way:
- The *opening* question is unaffected — a bare "yes" there still asks for one clarification, same as today.
- Everything else about identity handling (wrong number, third party, safety, refusal) is unaffected.
- No AI/prompt changes either way — this is purely the deterministic identity gate.
