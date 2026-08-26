# Submission

- Name: Sumit Chakraborty
- Submission date (YYYY-MM-DD): 2026-08-26
- Hours actually spent: 8.5 (6 building, 2.5 on this document and the screenshots)
- Repository / how to run it: https://github.com/Sumit-531/invoice-intake (see "Quick Start" in `README.md`; the pipeline itself is one command, `python -m src.main invoices/`)

## 1. Understanding the request

**What the client asked for.** Their accounting staff type supplier invoices into the
accounting system by hand, one at a time, every month. Month-end close turns into
overtime. Last month a typo almost made them pay the same invoice twice. They have heard
AI can read invoices now, and they want to see something working.

Taken at face value that is a small job. Read twelve documents with a model, send twelve
`POST /invoices`, give the staff their evenings back.

**What I built instead.** The sentence I kept going back to was not the one about
overtime. It was the one about almost paying twice. That sentence tells you what a mistake
costs here. It is not a bad row in a database. It is money that has already left the
company, noticed weeks later, and hard to get back. It also says the manual process has
come close once already.

Typing invoices by hand is slow, but it has one thing going for it. A person looks at
every document before it turns into a payment. If I automate the typing and stop there, I
have not added a check, I have removed one. In place of a careful clerk there is a model
that will read 5,400 where the invoice says 54,000 and not mention it. The invoices get
entered faster, and some of them get entered wrong.

So this is the problem I set out to solve:

> Register an invoice automatically when its numbers can be checked. When they cannot,
> stop it on my side, with a reason, before it reaches the accounting system.

Getting the text off the document is the easy half. Every current model reads a Japanese
invoice well enough, and I did not treat that as the risky part. The risk is what happens
after the model returns a number that looks fine and is not. That is where the time went:
a checking layer that recalculates every amount from the line items using the accounting
system's own formula, and a clear line between the invoices a machine may finish and the
ones a person has to see.

Three things followed from that, and they shaped the rest of the work.

**Duplicate invoices are a main feature, not an edge case.** The client named this fear in
the email, so I treated it as a requirement rather than a nice-to-have. The check runs
locally on `(partner_code, invoice_number)` before anything is sent. I did not want to
depend on the accounting system's `409` here, because that means trusting the boundary I
am supposed to be protecting. The sample set contains the same invoice twice in two
different formats. Both are read, and the second one stops.

**Full automation was never the goal.** What I want to be measured on is how few invoices
a person has to touch, and how well the rest are explained when they arrive. Of the twelve
samples, seven register on their own, one is caught as a duplicate, and four go to a
review queue with a reason code and the evidence attached. Those four are not a gap in the
system. They are the system doing its job.

**"I would like to see something working first" told me how much to build.** The email
asks for a working core, not a product. I read that as permission to leave out the review
screen, the database and any deployment, and to put the time into checking instead.
Section 3 covers what that decision cost.

## 2. What you would have asked the client

Each of these came up while building, not while writing this document. I wrote them down
at the time, with the assumption I made instead, because a question on its own reads like
I was stuck, and an assumption on its own reads like I never noticed.

| What you wanted to ask                                                                                                                | The assumption you made                                                                                                                             | Why                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| An invoice arrives from a supplier who is not in the partner master. Who adds them, and on what evidence?                             | Nobody, and not automatically. The invoice stops and goes to a person with the printed supplier name and registration number attached.              | Creating a partner code on the spot is how a payment reaches a bank account that nobody checked. Adding a supplier is a finance decision with its own approval. `invoice_10` in the sample set is exactly this case, and it is not a bug to fix.                                                                                                                                                                                                                        |
| A handwritten note changes the bank account. Does the printed detail win, or the handwriting?                                         | Neither, automatically. The note is transcribed, and the invoice goes to a person.                                                                  | The accounting API has no field for bank details, so the note cannot be acted on even if I read it perfectly. That also means nothing further down the line can catch it. On `invoice_08` every number verifies, but the printed account number is struck through in red. If I let it register, payment goes to the account someone crossed out.                                                                                                                        |
| The same invoice number arrives twice from the same supplier, with different amounts. Duplicate, or a corrected invoice?              | A duplicate. It stops. Identity is `(partner_code, invoice_number)`, and the amount is not part of it.                                              | The two cases need opposite handling. One should be ignored, the other should replace a record that is already registered. Guessing wrong means either paying twice or throwing away a correction. The accounting system also has no update, only insert, so a revision is not something I could act on anyway.                                                                                                                                                         |
| A supplier's printed total is one yen off from their own line items because they round tax differently. Register our figure, or stop? | Stop, and queue it.                                                                                                                                 | `invoice_09` prints 147,497 where the lines add up to 147,496. The supplier rounded tax up inside the total and printed the tax line rounded down. Both are defensible. Our accounting system rounds down, so submitting their number would be rejected anyway. The deeper reason is that a system which quietly overrides a supplier's total by one yen will eventually do it by more, and the point where that becomes unacceptable is a business decision, not mine. |
| If an invoice has no due date, are there standard payment terms per supplier?                                                         | No default. A missing due date is missing, and the invoice stops.                                                                                   | "Issue date plus 30" is the kind of default that looks harmless and quietly sets a payment date nobody approved. If terms do exist per supplier, they belong in master data where they can be checked, not as a constant in my code.                                                                                                                                                                                                                                    |
| What is the real monthly volume, and who works the review queue?                                                                      | Small. Twelve invoices across two months from five suppliers, so a few dozen a month, reviewed by the same accounting staff who type them in today. | This decides whether the thing stays a batch script or needs to become a service with a queue. At a few dozen a month, one command over a folder is the right answer. Section 7 estimates cost at 1,000 a month because the assignment asked for it, but nothing here is built for that rate, and I would rather say so than imply it scales.                                                                                                                           |

Reading these back, they are all the same shape. Something on the document is missing,
contradictory, or ambiguous, and I have to choose between guessing and stopping. I chose
stopping every time, including in a smaller case I have not listed: the accounting system
requires a unit on every line, and when a line does not print one, the only options are to
invent "式" or to stop.

That consistency has a cost worth being honest about. The system asks for a person more
often than a tuned one would, and if the client answered even three of these questions,
some of what now goes to the review queue would register on its own. I would rather hand
over a system that stops too often and can be loosened once someone tells me the rules,
than one that guessed early and has to be audited backwards.

## 3. Scoping decisions

**What you built**

I built this in vertical slices. Every session had to end with something that runs, so
that I was never holding half of one layer and none of the next. The order was picked by
risk, not by architecture.

**First, one invoice all the way through.** Get an API key working, read the text layer
out of a PDF, extract it, check it, POST it, and watch `invoice_01` appear in
`GET /invoices`. The key was the only real blocker here. Everything else had a workaround,
but a new account that hits billing verification or a low rate limit does not, and finding
that out on day one is cheap while finding it out on the last day is fatal.

**Second, the checking, before any breadth.** Recompute the subtotal, the tax per tax
code, and the total from the line items. Match the supplier against the partner master.
Then local duplicate detection, and width normalisation so a name read off a photo still
matches. All of it is pure functions with no network and no model call, so the tests run
offline in about five seconds with no API key. I could develop the checks against invoices
I made up and never spend a request doing it.

**Third, the other eleven documents.** A vision route for the scans, chosen by looking at
whether the PDF actually contains text rather than by trusting the file extension. One of
the samples is a `.pdf` with no text layer at all. Raw model output is written to disk
before anything parses it, so a bad run can be investigated without paying for the
extraction again.

**Fourth, the review queue.** Every invoice that stops produces a reason code and the
evidence behind it, written out as `out/review_queue.md` and `out/review_queue.json`. The
goal was that a person can act on a queued invoice without opening the original document.

Where that leaves it: `python -m src.main invoices/` reads all twelve. Seven register on
their own, one is caught as a duplicate before anything is sent, and four go to the queue.
The accounting system rejected none of them. That last number is the one I care about
most, because it means every stop happened on my side, which is the whole design. The test
suite is 111 tests, offline, no key required.

**What you left out, and why**

**The review screen.** The assignment lists this as one of the optional items where
candidates stand out, and I cut it on purpose. A screen needs something behind it: the
list of what stopped, why, and with what evidence. That part is built and is written to
disk on every run. The screen would be a rendering of a file that already exists. With the
time I had, I would rather hand over correct data and no interface than an interface over
data I had not finished checking. It is first in section 8 for the same reason.

**Retries, concurrency, a database, multi-currency, and authentication.** A failed model
call fails the invoice and says so, because a retry loop that hides a systematic failure
is worse than a stop. The twelve run one after another, paced for a free tier, since
parallel requests would only trip the rate limit. State lives in flat files in `out/`, and
the duplicate check reads its state from the accounting system rather than from a local
file, so there is nothing to keep. The API takes JPY only, and this runs as one command on
one machine for one operator.

**Any deployment at all.** This one is worth stating clearly because it can look like
laziness. The accounting system runs on `localhost:8080` on the evaluator's machine.
Anything I deploy to a cloud cannot reach it, and the assignment asks for a single command
to start it. Deploying would fail both requirements at once, so local is not a shortcut
here, it is the correct answer.

**Reading handwriting into fields.** Handwriting is detected and flagged, never
interpreted. A received stamp is noise and stays out of the payload. A note changing bank
details goes in front of a person. This is a line I decided on rather than a feature I ran
out of time for.

**Confidence as a gate.** The model reports how sure it is, and that routes an invoice. It
never approves one. A model that is confidently wrong is the exact failure this system is
built to catch.

The rule behind the order was simple. Anything that could kill the project got touched
first. Anything that only makes the output nicer got touched last. Extraction quality sits
in the middle, because once the checking layer exists it is safe for the model to be
wrong. I logged the time per session while working, so the hours at the top of this
document are measured rather than reconstructed at the end. They were six short sessions of
roughly one to two hours, fitted around a full-time job, which is exactly why every slice
had to end with something that runs. A half-built layer is one I would have had to page
back into memory two days later.

## 4. Design and technology choices

```
invoices/
   |
   v
does this file actually contain text?          (PyMuPDF)
   |                              \
   | yes: read the text layer      \ no: render the pages as images
   v                                v
   +----------------> one model call <----------------+
                            |
        raw response written to out/raw/ before anything parses it
                            |
                            v
              parsed into typed objects (Pydantic, integer JPY)
                            |
                            v
                      verify/  (pure, offline, no model, no network)
        arithmetic per tax code | partner master | dates | duplicate key | handwriting
                            |
             all clear      |      anything at all found
           +----------------+----------------+
           v                                 v
     POST /invoices                out/review_queue.md + .json
```

**Python**, because the accounting system I have to integrate with is a Python file, and
because PDF handling in Python is well travelled ground.

**PyMuPDF for both reading and rendering.** It answers the routing question, does this
file have a text layer, and renders pages to images when the answer is no. I chose it over
`pdf2image`, which needs a separate poppler binary on the machine. That is real friction
for anyone trying to run this, sitting right on top of the single command the assignment
asks for.

**Pydantic for the extraction schema**, so that an amount arriving as `1250.0` instead of
`1250` is a type error at the boundary rather than something I have to notice in review.
Money is an integer in yen everywhere in this codebase. There is exactly one float in it,
and it is deliberate, which I come back to below.

**Gemini Flash on the free tier** for extraction, and I want to be direct about how I
picked it. With twelve documents every provider costs close to nothing, so capability was
not the deciding factor. It was not the deciding factor for a second reason either: I do
not trust the output regardless of which model produced it, and the checking is arithmetic
against the accounting system's own formula, which is identical whoever generated the
numbers. So I chose on friction, and what decided it is that whoever evaluates this can
get a key in about two minutes with no credit card. Lowering the barrier for the person
running my code costs me nothing.

What I decided against, and why:

- **A paid Claude or OpenAI key.** Better in no way this particular task stresses, and
  worse for reproducibility, since the evaluator would need a funded account to run it.
- **Driving Claude Code headless as the extraction engine.** It would have used credits I
  already pay for, but nobody else could run the project without their own Claude Code
  login, which breaks the single command requirement outright.
- **A provider abstraction layer.** The model sits behind one function in
  `src/extract/gemini.py`. That is enough to swap it, and it lets me say honestly that the
  choice of model is not load bearing here. Building an interface with one implementation
  would have been architecture for its own sake. This turned out to matter in a small way:
  the model I started on stopped accepting new keys partway through, and moving to the
  current one was a one line change.

**The routing decision is about cost, not convenience.** A PDF that already contains text
must not be sent to a vision model, because that pays image prices for text I am holding
in my hand. So the route is chosen by looking inside the file, never by the extension. One
of the twelve samples is a `.pdf` containing nothing but a scan, and the extension would
have sent it down the wrong path.

**`verify/` has no network and no model in it, and that is the point.** It is pure
functions. I can test it against invoices I invent, instantly, offline, without an API
key, which is how it got built at all under a free tier that allows twenty requests a day.
If I ever find myself importing an HTTP client into that folder, I have solved a problem
in the wrong place.

**The one float.** The accounting system computes tax as `floor(subtotal_for_code × rate)`
using floating point. I mirror that exactly, including the float. Rewriting it in integer
arithmetic would arguably be more correct, and that is precisely why it would be wrong
here. The two versions can disagree at the rounding boundary, and when they disagree, the
accounting system is the authority and I am the one with the bug. My job is to predict
their answer, not to compute a better one.

## 5. How you used AI, and how you checked it

**What you delegated to AI**

Two different things, and it is worth keeping them apart.

**Reading the documents.** This is the obvious one. The instruction that matters here is
that the prompt describes hazard _classes_, never individual invoices. It tells the model
that Japanese era dates exist and that `令和8年2月5日` is a real date, that `△` and `▲` in
front of a number mean it is negative, that tax rates vary line by line inside one
invoice, that suppliers print their own name as an alias or short form, and that
handwriting should be transcribed but never applied to a field. There is a rule in the
project contract that I held to throughout: if a check only works because I knew which
file it was looking at, it does not work. No filename and no invoice number appears in any
branch anywhere in this codebase. There are two prompt versions, one for text and one for
images, versioned separately so that adding the vision route did not invalidate
extractions I had already paid for.

**Writing the code.** I used Claude Code for most of the implementation, and I want to be
straightforward about how. I did not ask it for an invoice parser. I wrote an engineering
contract first, committed it as `CLAUDE.md`, and worked from it every session. It states
the prime directive that every extraction error must fail locally and loudly before
anything reaches the accounting system. It ranks the verification methods, lists the
document hazards as classes, marks the accounting system's specification as locked and
owned by someone else, and fixes rules like money is always an integer, dates are
`YYYY-MM-DD` at every boundary, there are no silent defaults, and `verify/` may not import
a network client. That file is in the repository and is the most useful thing to read
alongside this document.

What I did not delegate is the part being judged. What the system refuses to do, where the
line between automatic and human sits, which checks outrank which, and what got cut. Those
are mine, and the contract exists so that they stayed mine across sessions.

**How you verified the output**

The starting position is that **a model cannot check its own extraction**. The extractor
and the checker share one understanding of the document, so a mistake that lives in that
understanding survives both of them. Asking a model to re-read a field it just misread is
not a second opinion. So the checks are ranked, strongest first, and the ranking is by how
independent each one is of the thing that produced the number.

|     | Check                                                           | Why it ranks there                                                                                                |
| --- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1   | Recompute subtotal, tax per code, and total from the line items | Deterministic, free, offline, and owes nothing to the model. Catches dropped lines, sign errors, and digit slips. |
| 2   | Match the supplier and tax codes against the master data        | External ground truth. The model cannot argue with a list it did not write.                                       |
| 3   | The accounting system itself, which recalculates and rejects    | Genuinely independent, but it costs a round trip and it arrives last, after the boundary.                         |
| 4   | The model's own stated confidence                               | A signal for routing. Never a gate. A confidently wrong model is the failure being defended against.              |

Checks 1 and 2 must pass locally before any POST is attempted. If the accounting system
ever returns a `422`, that is not an invoice to handle, it is a hole in my local checks,
and the fix belongs in the checks.

Then I broke things on purpose, because a check I have never watched fail is not a check.
I took extractions that were correct and sabotaged them one at a time. Flip a discount
from negative to positive. Move a date. Swap a tax code for one that does not exist. Drop
a line out of the middle. Eleven sabotage cases, eleven local stops, none of them reaching
the API. That run is one of the screenshots submitted with this document.

**A case where the AI got it wrong** (one example is enough, if you have one)

`invoice_12`. I did not have to manufacture this one.

The document prints a subtotal of 540,000, tax of 54,000, and a total of 594,000. The
model returned the tax as **5,400**. A dropped zero. Everything else on that invoice it
read correctly, including a `△ 30,000` discount line that it correctly reported as
negative, which is the hazard I had expected to be the hard part.

What makes it a useful example is which check caught it and which did not.

| Figure   | Printed | Recomputed from the lines | Agrees |
| -------- | ------- | ------------------------- | ------ |
| subtotal | 540,000 | 540,000                   | yes    |
| tax      | 5,400   | 54,000                    | **no** |
| total    | 594,000 | 594,000                   | yes    |

Two of the three figures agreed. A verifier that compared totals, which is the obvious
thing to build and what I would have built if I had not ranked the checks first, would
have waved this invoice straight through. Recomputing the tax per tax code as a separate
check is the only reason it stopped.

It is also worth saying what a model based check would have done. Asked whether 5,400
looks right for a 540,000 subtotal at ten percent, a second model call would probably say
no. But it would be re-reading the same image with the same understanding that dropped the
zero. The arithmetic never looked at the document at all, which is exactly why I trust it
more.

One honest caveat, because it cuts against me. I submit recomputed amounts rather than
printed ones, so had this invoice gone through, the figure registered would have been the
correct 54,000 anyway. Stopping it was still right, and the reason matters: **the check
cannot tell which of the two readings is wrong.** A misread line is exactly as consistent
with the evidence as a misread summary. Deciding to trust my own recomputation because it
looks more plausible is the precise reasoning this system exists to refuse. It goes to a
person.

## 6. Integrating with the accounting system

I treated the accounting system as though it belonged to another team and could not be
changed, because that is the realistic version of this situation. Its constraints shaped
my side rather than the other way round.

- **Dates are `YYYY-MM-DD` only.** Parsing happens once, at extraction, where
  `令和8年2月5日` and `2026年1月7日` and `2026/01/18` all become the same shape. From that
  point inward there is only one date format in the system.
- **Amounts are integers in yen.** Enforced by the schema at the boundary, so a decimal
  cannot get further in.
- **A tax code crosses the boundary, not a rate.** The invoice prints `10%`, the payload
  carries `T10`. A rate that maps to no code stops locally instead of being sent.
- **Only suppliers in the master may be registered.** I resolve against `GET /partners` by
  registration number first, since that is the strongest key on the document, then by name
  and by registered alias, with width normalisation so that a name read off a photo still
  matches. Nothing is ever created, and no near miss is accepted.
- **It recalculates every amount from the lines.** So I recalculate the same way first,
  using their formula including the floating point, and I submit figures I have already
  reproduced rather than figures I read off the paper.
- **Errors are structured.** I branch on the error code, never on the message text.

The duplicate rule is the one place I deliberately do more than the API asks. It returns
`409` on a repeated `(partner_code, invoice_number)`, but by the time that comes back a
payment instruction has already crossed into a system I do not own. So I build the key set
from `GET /invoices` at the start of a run, add each invoice as I register it, and check
locally before sending. The `409` stays as a backstop, and if it ever fires I treat it as
a hole in my own checks rather than as an invoice to handle.

| Invoice          | Result                           | How you handled it                                                                                                                                            |
| ---------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `invoice_01.pdf` | Registered, ACC-0001             | Text layer, no model image cost. All checks passed.                                                                                                           |
| `invoice_02.pdf` | Registered, ACC-0002             | Two pages, 26 lines. The line table spans both pages and the totals sit only on the last one.                                                                 |
| `invoice_03.pdf` | Registered, ACC-0003             | Two tax rates inside one invoice. Tax accrued per code, 8% and 10% separately, then summed.                                                                   |
| `invoice_04.jpg` | Registered, ACC-0004             | Scan, so it routed to the vision model.                                                                                                                       |
| `invoice_05.jpg` | Registered, ACC-0005             | Scan, vision route.                                                                                                                                           |
| `invoice_06.jpg` | Registered, ACC-0006             | Supplier printed as the short form `ヤマダ製作所`. Resolved to `P-1001` through the master's alias list.                                                      |
| `invoice_07.jpg` | Stopped as already registered    | The same invoice as `invoice_01`, arriving as a photograph instead of a PDF. Caught locally on the duplicate key before anything was sent.                    |
| `invoice_08.jpg` | Queued, `HANDWRITING_ANNOTATION` | The bank account number is struck through in red with a change written beside it. Every number on the invoice verifies correctly. It still must not register. |
| `invoice_09.pdf` | Queued, `TOTAL_MISMATCH`         | A `.pdf` containing only a scan, routed to vision after zero characters were detected. Prints 147,497 where its own lines give 147,496.                       |
| `invoice_10.jpg` | Queued, `PARTNER_NOT_FOUND`      | `新星ロジスティクス株式会社` is not in the master under its name, any alias, or its registration number.                                                      |
| `invoice_11.jpg` | Registered, ACC-0007             | Era date `令和8年2月5日`, converted to `2026-02-05` at extraction.                                                                                            |
| `invoice_12.jpg` | Queued, `TAX_MISMATCH`           | Tax read as 5,400 against 54,000 recalculated from the lines. The dropped zero from section 5.                                                                |

Seven registered, one stopped as a duplicate, four sent to a person. **The accounting
system rejected nothing.** Every stop happened locally, before the boundary, which is the
result the whole design is aiming at.

**What happens to the ones that could not be registered.** Each writes an entry to
`out/review_queue.md` and `out/review_queue.json` holding what was read, the reason code,
the evidence behind it, what the reviewer has to decide, and, explicitly, what the system
declined to do. That last part matters more than it looks. On `invoice_10` it records that
no partner was created and no near miss was accepted. On `invoice_08`, that the
handwriting was transcribed and never applied, and that no bank detail was read off a
photograph. The queue rebuilds from the stored run records with `python -m src.review`,
which spends no model requests and does not need the accounting system running.

One distinction inside those five is deliberate. Four need a person. The duplicate does
not. Nothing is wrong with `invoice_07`, the system reached the right answer by itself, and
sending a reviewer to look at it would have them hunting a fault that is not there. It is
listed for completeness and kept out of the action list, because a queue that raises things
nobody needs to act on stops being read.

## 7. Cost, limits, and risk in production

These are measured from the real batch, not estimated. I instrumented the first run rather
than the last one.

- **Cost per invoice.** One model call, and nothing else costs anything. Measured across
  the twelve documents: the text route ran from 3,085 tokens for a one page invoice to
  6,383 for the two page one with 26 lines, typically around 4,100. The vision route ran
  from 3,630 to 5,188, typically around 3,900. So roughly **4,000 tokens per invoice**,
  which on any current Flash class model is a fraction of a cent, and on the free tier is
  zero. I have given token counts rather than a money figure on purpose, because the price
  per token is the least stable number in this document and the token count is not.

  Two things in that data cut against the obvious story. **The route matters less than the
  document does.** A two page text invoice cost more than every vision page in the set,
  because line count drives the response while page images drive the prompt, and on single
  page documents those roughly cancel. Routing on the text layer is still right, since it
  is free and avoids image tokens, but it is not the large saving it looks like on paper.
  And **latency is not a proxy for cost**: the slowest call, at 158 seconds, cost 5,188
  tokens, while a 10.7 second call cost 3,669.

- **Monthly cost at 1,000 invoices per month.** About 4 million tokens, which at Flash
  class pricing is single digit dollars. The model is not the expensive part. **The real
  cost is the review queue.** Four of these twelve need a person, and if that ratio held, a
  thousand invoices a month would put roughly 330 documents in front of someone. At a few
  minutes each that is close to two days of their month, which dwarfs the API bill. The
  honest caveat is that this sample is deliberately loaded with hazards, so a real month
  would queue a much smaller share. It still sets the direction: reducing the queue rate is
  worth far more than reducing tokens, and answering the questions in section 2 would
  reduce it for free.

- **Processing time per invoice.** The model call is the whole of it. Median around 15
  seconds, ranging from 10.7 to 158 across the batch. Everything after it is arithmetic on
  local data and takes no measurable time. A full run of twelve takes a few minutes, most
  of that spent pacing requests to stay inside 5 per minute.

- **Where this breaks first.** Rate limits, and not narrowly. The free tier allows 20
  requests a day, so one batch of twelve consumes more than half a day's budget with no
  room to re-run. That wall arrives at about 20 invoices a day, well before anything else
  strains. A paid key moves it to requests per minute, at which point the sequential design
  becomes the limit. A quieter one is worth naming: I seed the duplicate key set by calling
  `GET /invoices` at the start of every run. Against a mock holding seven records that is
  free. Against a real system holding years of invoices it is not, and it would have to
  become a lookup on the specific key. The mock let me get away with something the real
  system would not.

- **How you would find out if something was registered incorrectly.** Today, by looking,
  and I would rather say that plainly. The trail exists: every run writes a record to
  `out/runs/` with the raw model response, the parsed extraction, every check that ran, the
  payload sent, and the `accounting_id` returned, so any registered invoice traces back to
  the raw text without paying to extract it again. What does not exist is anything
  watching. In production I would add three things in this order. A reconciliation
  comparing what the accounting system holds against my run records, since a disagreement
  there is the only true signal. Alerting that separates a misextraction, which should wake
  someone, from an already registered document, which should not. And a monitor on the
  queue rate, because if the share of stopped invoices suddenly falls, the likeliest
  explanation is that a check stopped firing, and that failure looks exactly like success.

  The error this design cannot catch is worth naming. The arithmetic compares the line
  items against the printed summary, so it catches a misreading of either one. It cannot
  catch a misreading of **both in the same direction**, since the two would still agree.
  That needs the same mistake twice in two different places on the page, but it is the
  residual risk, and it is why check 3 is worth keeping as a backstop rather than dismissed
  as redundant.

## 8. What you would do with another 8 hours

1. **The review screen, and with it a way to correct an invoice and send it on.** This is
   the thing I cut, and it is first because of what section 7 says about cost. The model
   bill is a few dollars a month; the queue is days of someone's time, and a screen is the
   only item here that attacks the expensive part. There is also a real gap in the loop
   today: an invoice that stops has no way back in except for a person to type it into the
   accounting system by hand, which is the exact work the client asked to be rid of. The
   data behind the screen already exists and is written on every run, so this is building
   the missing half rather than starting something new.

2. **Reconciliation and alerting.** Compare what the accounting system holds against my own
   run records on a schedule, alert when they disagree, and make a misextraction wake
   somebody while an already registered document does not. Second rather than first on
   purpose: right now a person sees every document that stops, so the system is watched by
   the fact that it is small. That stops being true as volume grows, and this has to exist
   before it does. But it guards against a failure that has not happened yet, while item 1
   removes work happening today.

3. **Turn resolved queue items into a regression set.** Every invoice a human resolves is a
   document with a known correct answer attached. Kept as test cases, those turn the queue
   from a cost into an asset, and make it possible to say whether a prompt change actually
   improved anything instead of asserting it did. Third because it compounds rather than
   fixes: worth little in the first month and a great deal in the sixth, and it only works
   once item 1 exists to capture what the reviewer decided.

The order is the same reasoning throughout. Remove work that exists now, then guard against
the failure that is coming, then make both of those measurable. What still would not make
the list, even with another eight hours: retries, concurrency, multi-currency, or a second
model checking the first. The last one sounds like the obvious next safety feature and is
the one I would refuse, for the reason given in section 5.
