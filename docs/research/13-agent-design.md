# 13 — Agent design: goal versus rules, instruction overload, voice vendors, discovery, the model-never-computes split

Researched 2026-09-14 against vendor guidance, published benchmarks, fintech engineering writeups, counselling standards, and this repo's own code and eval suite. `gpt-5.6-luna` is not publicly documented, so the GPT-5.x
guides are the nearest public analogue **(unverified)**. Claims the sources did not settle are marked **(unverified)**.

## Decision summary

- **Rules stay, the mood changes.** Every vendor publishing prompt guidance says to state the behaviour wanted rather than enumerate prohibitions, and the strongest warning is that an open-ended prohibition makes the
  model over-index and suppress wanted behaviour. `Never invent, add, subtract, round or estimate` is that form.
- **Conditionality, not length, is the load.** 620 tokens is inside every vendor threshold. Benchmarks price branching: flat conjunctions are nearly free, conditional and selection rules collapse compliance. The prompt
  is mostly conditionals.
- **"Results beat prompts" does not survive the literature as stated.** The advantage is real; the causal account in `CLAUDE.md` is probably wrong. Defensible restatement: the winning channel is the one that is
  **specific, non-conflicting and present at the moment of action**, not the imperative mood.
- **No node graph.** One vendor is retiring its flow product with a public reason, a second compiles its flow back into a single prompt, a third's four split signals are all absent here.
- **The money split is the strongest asset.** Four shipped fintech systems draw the same line. Keep it, and add the *components* of every computed figure so a figure can be explained without being recomputed.
- **The eval suite defines the product.** All sixteen checks are constraint checks; optimising against that suite produces a rule-follower by construction.

## 1. Vendor guidance: rule lists versus goals

**1a. Instructions over constraints.** Google's prompt whitepaper is the most direct statement and is against prohibition lists: *"focusing on positive instructions in prompting can be more effective than relying heavily
on constraints... constraints might leave the model guessing about what is allowed... Also a list of constraints can clash with each other"*, with constraints only *"when necessary for safety, clarity or specific
requirements."* https://archive.org/stream/whitepaper-prompt-engineering-v-4/whitepaper_Prompt%20Engineering_v4_djvu.txt Anthropic's example matches this prompt almost verbatim: *"Tell Claude what to do instead of what
not to do. Instead of: 'Do not use markdown in your response'. Try: 'Your response should be composed of smoothly flowing prose paragraphs'"*, plus *"Where you might have said 'CRITICAL: You MUST use this tool when...',
you can use more normal prompting"* and *"Remove over-prompting."* https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices The repo carries `No lists, no markdown, no
abbreviation you wouldn't say aloud`, the named weak form. Gemini 3 goes further: prohibitions *"like 'do not infer' or 'do not guess' may cause the model to over-index on that instruction and fail to perform basic logic
or arithmetic or synthesize information."* https://docs.cloud.google.com/vertex-ai/generative-ai/docs/start/gemini-3-prompting-guide A prohibition suppressing *wanted* behaviour is the exact shape of "goes silent when a
rule does not fit". **Right altitude** (Anthropic, context engineering): be *"specific enough to guide behavior effectively, yet flexible enough to provide the model with strong heuristics"*, avoiding both *"hardcoding
complex, brittle logic in their prompts"*, which brings *"fragility and increases maintenance complexity"*, and *"vague, high-level guidance"*; aim for *"the minimal set of information that fully outlines your expected
behavior"*, since *"minimal does not necessarily mean short."* https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

**1b. Constrain versus trust.** Workflows are *"orchestrated through predefined code paths"* and buy *"predictability and consistency for well-defined tasks"*; agents *"dynamically direct their own processes and tool
usage"* and fit *"open-ended problems where... you can't hardcode a fixed path."* https://www.anthropic.com/engineering/building-effective-agents The multi-agent writeup names the principle, *"instilling good heuristics
rather than rigid rules"*, graded on outcome rubrics rather than procedural steps because multiple valid paths reach the correct answer. https://www.anthropic.com/engineering/multi-agent-research-system OpenAI's GPT-5
guide gives the mechanism for the silence symptom: *"poorly-constructed prompts containing contradictory or vague instructions can be more damaging to GPT-5 than to other models, as it expends reasoning tokens searching
for a way to reconcile the contradictions"*, and fixing this *"drastically streamlined and improved their GPT-5 performance."* https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide At effort `none`
the model *"never use[s] reasoning tokens"*, so contradictions are not silently repaired and prompted planning matters more because *"the model has fewer reasoning tokens to do internal planning."*
https://developers.openai.com/cookbook/examples/gpt-5/gpt-5-1_prompting_guide **The dissent is real:** OpenAI's practical agents guide recommends routines from standard operating procedures, *"Define clear actions...
even the wording of a user-facing message"*, *"Capture edge cases... conditional steps or branches."* https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf Its worked examples are
refunds and call centres, where a script *is* the product, which is my reason to discount it **(unverified)**; its own escape hatch applies here, *"When prompts contain many conditional statements... consider dividing"*.

**1c. Tools as the locus of determinism.** Anthropic asks for investment in the *"agent-computer interface"* on a par with human interface work, and says to *"Poka-yoke your tools"* and, on results, *"return only high
signal information"*, noting agents *"grapple with natural language names... significantly more successfully than... cryptic identifiers"*, that *"You can prompt-engineer your error responses to clearly communicate
specific and actionable improvements"*, and on truncation *"be sure to steer agents with helpful instructions."* https://www.anthropic.com/engineering/writing-tools-for-agents That is the closest published endorsement of
result-carried steering, but it covers errors and truncation notices, not imperative scripts for what to say next **(unverified)**. OpenAI 5.2 adds the restate-after-write pattern: *"After any write/update tool call,
briefly restate: What changed, Where."* The repo's `recorded rent 12,000 due 5 Oct; say this back, then ask` is that pattern with an imperative bolted on. **1d. Which is this?** By these definitions the product is a
workflow wearing an agent's clothes **(unverified, a reading not a vendor classification)**: question order fixed by `missing:`, the plan gated by `blockers:`, the next speech act dictated by a result string. The one
genuinely agentic call left, correction versus contradiction and plausibility, is exactly the part that reads as intelligent.

## 2. Instruction overload: the measurements

- **Constraint count.** FollowBench adds one constraint per level; GPT-4-1106 hard-satisfaction runs 84.7, 75.6, 70.8, 73.9, 61.9 across L1 to L5, and *"the instruction-following upper bound for GPT-4 and GPT-3.5 is
  approximately 3 constraints."* https://aclanthology.org/2024.acl-long.257/
- **Rule shape beats rule count.** ComplexBench, GPT-3.5 DRFR: 1 And 0.845, 1 Chain 0.686, 1 Selection 0.682, 2 Selections 0.377, And plus Chain plus 2 Selections 0.083. *"the addition of And has a limited impact on the
  overall complexity"*: flat conjunctions are cheap, branching collapses. https://arxiv.org/abs/2407.03978 This prompt is mostly conditionals ("If a value differs...", "If an amount sounds implausible...", "If a result
  tells you what to say...").
- **Count crossed with placement.** Prompt Design at Scale, Sonnet 5 perfect-response rate: 93.8% at 10 rules, 75.0% at 20, 23.8% at 40, 0% at 80, and *"Every model, every format, and both placements are effectively at
  zero perfect-response rate by N=80."* https://arxiv.org/abs/2607.19257 Weak: five models, synthetic, not peer-reviewed, "perfect response" compounds **(unverified)**. Its placement effects are model-specific with no
  universal winner, so it cannot be cited as "the user turn wins".
- **Omission, not violation.** IFScale: the best frontier model reaches only 68% at 500 instructions, and the omission-to-modification ratio rises 12.0 to 34.9 between 50 and 500 instructions. Models silently drop rules.
  https://arxiv.org/abs/2507.11538
- **Decay across turns, the class most relevant to a voice call.** Multi-IF loses roughly 7 to 11 points per turn, every model, monotonic (GPT-4o 0.843, 0.724, 0.631) https://arxiv.org/abs/2410.15553 ; SysBench
  compliance by round: GPT-4o 84.8%, 68.5%, 53.1%, 43.3%, 33.7%, Claude-3 Opus 82.3% to 28.4% https://arxiv.org/abs/2408.10943 ; MMMT-IF 0.81 at turn 1 to 0.64 at turn 20 https://arxiv.org/abs/2409.18216 . This is the
  strongest mechanism for the repo's own finding: a rule sitting only in the system prompt is largely gone by turn 20, and the same rule re-delivered one turn before it is needed is not.
- **Position.** Lost in the Middle finds a U-shaped curve where *"performance can drop by more than 20%"*, worst case below closed-book https://aclanthology.org/2024.tacl-1.9/ ; weaker but present in NoLiMa (GPT-4o 99.3%
  to 69.7% at 32K, https://arxiv.org/abs/2502.05167) and Chroma's Context Rot, *"All 18 models exhibit performance degradation at every input length increment tested"* https://research.trychroma.com/context-rot .
  Anthropic claims a query placed after long data *"can improve response quality by up to 30 percent in tests"*, a vendor claim with no published method **(unverified)**.
- **Conflicts are the expensive case.** IHEval: conflicting instructions cost GPT-4o 21.9 points, Claude-3 Sonnet 55.2, Llama-3.1-70B 78.3, while an *aligned* hierarchy costs about 1 point. Hierarchy is free until rules
  disagree, then catastrophic. https://arxiv.org/abs/2502.08745
- **The finding that cuts against this repo.** OpenAI's Instruction Hierarchy trains the order System, User, multimodal, then text from tools and retrieved documents, lowest. https://arxiv.org/abs/2404.13208 No published
  benchmark supports "instructions in tool results beat prompt-only instructions"; the nearest published work points the other way, and the repo's 0-to-80 versus 96-to-100 matrix is the primary evidence. Cite recency,
  per-turn forgetting and omission-under-density as *mechanism*, never as corroboration.
- **Negative instructions.** Vendors are unanimous; the academic evidence concerns *comprehension* in pre-frontier models: inverse scaling on negated prompts (https://arxiv.org/abs/2209.12711), negation as late-emergent
  (https://aclanthology.org/2023.findings-acl.472/), and models that *"possess internal components that process negation correctly"* but fail via *"late-layer attention behavior that promotes simple shortcuts"*
  (https://arxiv.org/abs/2605.03052). No benchmark A/B-tests "do not X" against a positive reformulation of the same rule **(unverified)**. That delta is this repo's to measure.
- **Over-constraint to over-refusal.** OR-Bench finds Spearman 0.878 between safety scores and over-refusal, XSTest shows refusal on lexical overlap alone, and both sit in the safety domain, so applying them to product
  rules is extrapolation **(unverified)**. "A rule with no matching case makes the bot stall" is essentially unstudied, the nearest signals being Chroma's finding that Claude 4 models abstain more under ambiguity and the
  Gemini "do not infer" note. Thinnest claim here. Measure it.

## 3. Voice platforms: flow versus single prompt

**Vapi is retiring its graph product:** *"Workflows will be retired on August 18, 2026... We no longer recommend Workflows for new builds"*, because *"current AI systems aren't yet capable of... 1. Maintain awareness of
the current node's instructions 2. Understand all possible next steps."* Migration advice is to consolidate, *"Start by bundling as much of the workflow as you can into a single assistant... If two stages would
repeatedly hand off to each other, consolidate them into one assistant"*, since frequent cyclical handoffs add latency and can introduce hallucinations. https://docs.vapi.ai/workflows/overview **Retell concedes it
structurally** through Flex Mode, which *"compiles that flow into one structured prompt made of Tasks and available Tools"* for users who complete tasks out of order or several at once
https://docs.retellai.com/build/conversation-flow/flex-mode : a vendor admitting a rigid graph cannot handle real conversation, and fixing it by collapsing the graph back into a prompt. **LiveKit gives the cleanest
rule:** *"Start with a single agent and a small set of tools. A single agent can handle multi-step flows by updating its instructions or changing available tools between conversation phases"*, splitting only on four
signals, instruction bloat, conflicting tool access, multi-turn structured data collection, backtracking. https://docs.livekit.io/agents/logic/workflows This product hits none of the four **(unverified, my assessment)**.
**Pipecat Flows argues the other way** and is the framework in use: *"monolithic prompts with many tools lead to hallucinations and lower accuracy"* https://docs.pipecat.ai/pipecat/flows/introduction , with no "when not
to use Flows" section, on a product page; Pipecat publishes no prompt guidance at all, zero hits for "prompt engineering" in https://docs.pipecat.ai/llms.txt

**"One question at a time" is vendor-recommended**, explicitly by Vapi (https://docs.vapi.ai/prompting-guide), Retell (https://docs.retellai.com/build/prompt-engineering-guide) and LiveKit (*"Keep replies brief by
default: one to three sentences. Ask one question at a time."* https://docs.livekit.io/agents/start/prompting); not stated by ElevenLabs or Pipecat. Keep the rule. What no vendor recommends is a **fixed order**; that is
this repo's own addition, and the form feel comes from the ordering, not the one-question rule. Vapi draws the distinction this product needs: *"Use read-backs when: the data has to be exact... Skip read-backs when:
you're collecting intent, preference, or soft qualification data"*, because otherwise *"that turns the call into a form."* On **banlists**, Vapi alone gives a mechanistic warning: *"Long enumerated 'never say X, Y, Z'
lists are an anti-pattern... the verbose ban effectively becomes a menu of likely outputs. Prefer a short positive principle..."*, three to five items plus a principle clause; asserted with no data, and ElevenLabs and
LiveKit ship "Never..." lists in their own templates **(unverified)**. On **length** the warnings are unanimous: ElevenLabs *">2000 tokens increase latency and cost"*, Retell *">1000 words, switch architecture"*, LiveKit
*"instruction bloat"*, Vapi *"Models lose focus with too many and potentially conflicting instructions"*. The 620-token ceiling is inside every threshold, so length is not the problem; about 30 imperative lines in 620
tokens is a far higher rules-per-token ratio than any vendor template, whose length goes mostly on identity, examples and context. On **persona**, LiveKit: *"LLMs are already trained to be friendly and helpful, so
prompting for those traits is redundant. Show the agent how to behave instead. Define personality as observable speech patterns: which words it uses, how it starts sentences, how it recovers from misunderstandings."* `a
calm money coach` spends tokens on an adjective and says nothing about how a coach opens, reflects or recovers. **On result-carried instructions, no vendor has measured it**: the four nearest supports all put the burden
on the tool *definition* (Retell, ElevenLabs, LiveKit, Vapi), so the repo's finding appears novel relative to published guidance, worth saying carefully at n=5 per cell.

## 4. "The model must not compute"

**Cleo states the principle almost verbatim:** *"Cleo operates as an agentic system that routes all calculations through deterministic tools built for financial data. The LLM's role is strictly interpretive: parsing the
query, formatting the output, not doing the math."* https://web.meetcleo.com/blog/cleo-vs-the-rest-evaluating-ai-models-on-real-world-money-questions With numbers: over 129 transactions and 21 data points, Cleo scored
17/21, GPT-4o 13, Claude Sonnet 4 7, Gemini 6, and one model *"confidently reported that a user spent over $28,000 on bills last month. The actual total? Just over $3,000."* **Bank of America (Erica)** sets the bar: *"we
can't afford to be 90% right. Clients expect our answers to be 100% right, 100% of the time"*; *"Erica will continue to be primarily a deterministic natural language processing system"*; *"nothing generative goes in
front of clients."* https://www.bankingdive.com/news/bank-of-america-erica-virtual-assistant-ai/758519/ **Intuit** has a tax engine codifying *"more than 100,000 pages"* compute while Claude explains.
https://aws.amazon.com/blogs/machine-learning/intuit-uses-amazon-bedrock-and-anthropic-claude-to-explain-taxes-in-turbotax-to-millions-of-consumer-tax-filers/ **Capital One Chat Concierge** splits into *"one agent
conversing with the customer, one building an action plan from business rules, one evaluating accuracy, and one explaining and validating the result."*
https://www.capitalone.com/tech/ai/agentic-ai-the-next-frontier-in-generative-ai/ **Monzo** ships output guardrails with human handoff, a 100-conversation golden set, and, matching this repo's fakes rule, a simulated
tool environment where *"blocking a card updates its status so future tool calls receive accurate responses."* https://monzo.com/blog/engineering-the-future-of-customer-operations-the-monzo-ops-agent **Albert** routes
advice to licensed humans. https://albert.com/about/genius

**Vendor nearest-statements.** Anthropic triggers code execution on *"Non-trivial math (large numbers, many steps, precision-sensitive results)"*
https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool and warns Claude *"might guess values you didn't supply."* Academic grounding: PAL (https://arxiv.org/abs/2211.10435) *"offloads the
solution step to a runtime"* because models *"often make logical and arithmetic mistakes in the solution part, even when the problem is decomposed correctly"*; Program of Thoughts (https://arxiv.org/abs/2211.12588), on
three financial-QA datasets, gains about 12% over chain of thought. No vendor says "the model must not compute" in those words; Cleo comes closest. **"Show your derivation" is not a named published pattern**
**(unverified)**; the nearest structural analogue is Anthropic Citations, whose framing transfers exactly, *"guaranteed to contain valid pointers"* and *"significantly more likely to cite the most relevant quotes... than
purely prompt-based approaches"* https://platform.claude.com/docs/en/build-with-claude/citations : a vendor admitting a structural mechanism beats a prompt instruction, the same shape as this repo's measurement.
Returning a figure *and its components*, so the model can explain without recomputing, is this repo's own contribution. **Regulated advice.** FINRA 2111.04: a recommendation may be made *"only if... has sufficient
information about the customer to have a reasonable basis to believe that the recommendation is suitable"*, and any omitted factor must be *"documented with specificity."*
https://www.finra.org/rules-guidance/rulebooks/finra-rules/2111 "We didn't ask" is never a defence, making discovery a regulatory argument and not only a usability one. No published fintech writeup describes code-level
enforcement of advice refusal **(unverified)**; the examples are prompt-level (Klarna), architectural avoidance (Bank of America), guardrail plus handoff (Monzo) or human routing (Albert).

## 5. Discovery in advisory conversations

**Every professional body runs picture, then priorities, then plan, and treats unknown as a state.** CFP Board's 2019 revision re-ordered its process so understanding circumstances is Step 1 and goal-setting Step 2, and
the re-ordering is itself the citation for facts-before-goals; Standard C.1.c, *"Addressing Incomplete Information. If unable to obtain information necessary... must either limit the Scope of Engagement... or terminate
the Engagement"*, gives two options, neither of which is skipping data gathering. https://www.cfp.net/-/media/files/cfp-board/standards-and-ethics/cfp-code-and-standards.pdf AFCPE's largest competency domain is *"Set the
Stage and Gather Client Information (15%)"*. https://www.afcpe.org/certification/accredited-financial-counselor/afc-core-competencies/ CFPB says coaches use the client's goal as a jumping-off point *"as opposed to a
series of prescribed steps or a set curriculum"*, and, crucial for a one-call product, *"Many clients only attended the initial session"*; its intake tool makes "I don't know" a first-class selectable answer and says
*"ask the client to prioritize them with you."* https://files.consumerfinance.gov/f/documents/102016_cfpb_Financial_Coaching_Strategy_to_Improve_Financial_Well-Being.pdf

**MI, the Miller and Rollnick counselling method, says plan last and optionally.** Miller and Moyers: *"Can it be MI without... Engaging? No / Focusing? No / Evoking? No / Planning? Yes."*
https://www.motivationalinterviewing.org/sites/default/files/Teaching%20the%20Four%20Processes.pdf SAMHSA TIP 35: *"Do not jump into the planning process if the client expresses enough sustain talk to indicate not being
ready"*; *"Before you jump in with your ideas, elicit the client's ideas"*; and the righting reflex, *"the natural impulse to jump into action and direct the client toward a specific change. Such a directive style is
likely to produce sustain talk and discord."* https://www.ncbi.nlm.nih.gov/books/NBK571068/ The named failure mode is the Premature Focus Trap, *"focusing before engaging, trying to direct before you have established a
working collaboration."* **Permission before advice is a defined construct** with an expiry rule precise enough to implement: MITI codes advice *"without an explicit statement or strong contextual cue emphasizing the
client's autonomy"* as Persuade, and permission *"may last for several minutes"* but lapses if the clinician *"changes the topic, becomes more directive... or starts prescribing a plan without again asking permission."*
https://motivationalinterviewing.org/sites/default/files/miti4_2.pdf MI allows either an explicit ask or *prefacing*, an autonomy-supporting statement that does not wait for an answer, which matters when a turn costs
latency. **Summaries**: TIP 35's checking instruction is *"At the end of a summary, ask the client whether you left anything out"*, an open repair invitation rather than a comprehension quiz, and *"Did I get that
right?"* and *"What did I miss?"* are **not** in primary MI sources. For comprehension, AHRQ teach-back is the standard and its rationale transfers: *"When patients are asked, 'Do you understand?' they often indicate
they do when they may not."* https://www.ahrq.gov/health-literacy/improve/precautions/tool5.html The repo's prompt says *"Never ask them to repeat it back"* and treats a yes as understanding, the opposite of teach-back:
defensible for a voice call, but a deliberate trade worth naming.

**Evidence caveat.** Two meta-analyses agree on a result that is not the one usually claimed: MI skills predict change talk at r=.26/.17, but change talk to outcome is null (r=.06 p=.41; r=-.05 with a CI crossing zero),
while sustain talk predicts worse outcome at r about -.23 to -.24. https://pmc.ncbi.nlm.nih.gov/articles/PMC4237697/ https://pmc.ncbi.nlm.nih.gov/articles/PMC6039097/ The defensible claim is "avoid producing sustain
talk", not "evoke change talk and outcomes follow". No study isolates premature advice-giving as a cause of worse outcomes **(unverified)**; the citable chain is three links (MITI codes it, TIP 35 says it produces
sustain talk, sustain talk predicts worse outcomes). **Encoding discovery as coverage rather than a checklist is a solved research problem.** SparkMe frames utility as *"a trade-off between coverage of a predefined topic
guide, discovery of relevant emergent themes, and ... cost (length)"*, notes existing systems *"lack a principled mechanism for balancing systematic coverage of predefined topics with adaptive exploration"*, and reports
4.7% more coverage with fewer turns over 70 participants. https://arxiv.org/abs/2602.21136 SAGE-Agent defines structured uncertainty over tool parameters and their domains and prices each candidate question by expected
value of information: 7 to 39% higher coverage with 1.5 to 2.7 times fewer clarifying questions. https://arxiv.org/abs/2511.08798 Uncertainty over tool parameters is exactly "what is missing, owned by code", but used to
*rank* questions rather than *order* them rigidly. MIBot, fully generative, reached MI adherence in 98% of utterances, higher than human counsellors, over 106 participants https://aclanthology.org/2025.findings-acl.1283/
: strong evidence a scripted checklist is not needed for method consistency. Counterpoint, to engage rather than ignore: Wasenmüller et al. argue free-running LLMs *"inherently lack the ability to (a) consistently and
reliably act by predefined rules... and (b) make their decision paths inspectable for risk management."* https://arxiv.org/abs/2412.15242 **Letting the model keep its own plan**: Anthropic recommends *"Structured
note-taking... where the agent regularly writes notes persisted to memory outside of the context window"*, while the Agent SDK cuts the other way, *"Newer models track multi-step work without a written todo list."*
https://code.claude.com/docs/en/agent-sdk/todo-tracking OpenAI's deep research ships a clarifying agent told to *"ask 2-3 clarifying questions"* and, directly relevant, *"If certain attributes are essential for a
meaningful output but the user has not provided them, explicitly state that they are open-ended"* and *"Avoid Assumptions: If the user has not provided a particular detail, do not invent one."*
https://developers.openai.com/cookbook/examples/deep_research_api/introduction_to_deep_research_api_agents

## 6. Push-back: re-read the repo's own measurement first

The headline, result-carried 96 to 100% against prompt-only 0 to 80%, is real. The causal account in `CLAUDE.md` is probably wrong, and the wrong account is now driving design. Four objections:

1. **Confound.** The result-carried version differs on four axes at once: placement (fresher), conditionality (it appears only when it applies), specificity (it names the field) and mood (imperative). The measurement
   isolates none of them.
2. **The clearest cases are conflicts, not placement.** `implausible_amount_confirmed` sat at 0/5 because the result said `say this back, then ask` while the prompt said confirm if implausible: two rules, one turn, one
   question. Moving the rule into the result did not "beat the prompt", it removed a contradiction, which IHEval prices at 22 to 78 points against about 1 point for aligned hierarchy. `changed_value_acknowledged` on
   balances is the same effect in reverse: `CONFIRM_CHANGE` scored 0/5 because the instruction was *wrong for the case*, and the model was right to refuse it.
3. **Decay explains the rest.** Multi-IF (-7 to -11 points per turn), SysBench (85% to 34% by round 5) and MMMT-IF (0.81 to 0.64 by turn 20) say a system-prompt rule is largely gone late in a call. `one_goodbye` at 28%
   rising to 100% is a turn-20 rule.
4. **Statistics.** n=5 per cell, and 5/5 has a 95% CI of roughly 48 to 100%. `amounts_repeated` ran 80, 40, 68, 96 across variants: non-monotone, so instructions interact.

**The defensible restatement:** the channel that wins is the one that is **specific, non-conflicting and present at the moment of action**, not the imperative mood. The measured advantage can then be kept while the
bossiness is dropped, since bossiness was never the active ingredient. A reading, not a measurement **(unverified)**, but the one most consistent with the repo's own provenance table.

## 7. Structural findings from the code

- **Every tool is a write.** All seven handlers mutate state or end the call. There is no read-only query tool, so the model can only learn something at the instant it records something. "Cannot explain its own numbers"
  is not a prompt failure, it is architectural: the prompt says *"If a figure is not in a result, do not say it"*, and nothing lets the model **ask**.
- **Nobody owns completeness of the picture.** `missing_fields` lists gaps only on items *already recorded*; it cannot name a category the person never mentioned. `blockers` is opening balance plus income. So
  `READY_TO_PLAN` fires almost immediately, patched by one nudge (*"ask once, then finalize_plan"*). That is why it plans too early, and FINRA 2111.04 says "we didn't ask" is not a defence.
- **All 16 eval checks are constraint checks.** Not one measures whether the call was *useful*: no coverage, no explanation quality, no did-they-understand. Optimising against that suite produces a rule-follower by
  construction. Anthropic grades outcome rubrics precisely because multiple valid paths reach the correct answer.

## 8. Recommendation

**8.1 The split.** Code keeps money, dates, priority order and the figures in results, the line the cut brief drew and the one Cleo, Bank of America, Intuit and Capital One all confirm. Add the *components* of every
computed figure, so a derivation is served without the model recomputing: the Citations pattern applied to arithmetic. Remove the *ordering* of `missing_fields` as a question queue, keeping the set and dropping the
queue, since no vendor recommends a fixed question order and the failing case that justified the prompt rule ("four questions at once") only ever justified one at a time. The model gains what to ask next, when the
picture is complete enough to plan, whether to summarise or press on, whether to ask leave before advising, and how to explain a number: language calls where a wrong move costs naturalness, not money, the cut brief's own
test.

**8.2 Tools: add queries.** Additive. `get_state()` / `coverage()`, read-only, returns what is recorded, what is missing and what has never been asked about, as facts with no imperative. `explain(figure)` returns a
figure with its components and the rule applied (`shortfall 4,200 = essentials 18,000 + debts 6,200 - income 20,000; card minimum 1,800 reserved on 5 October`), fixing "cannot explain its own numbers" without the model
doing arithmetic, since every component is already in the engine. `note_agenda(topics)`, a scratchpad of what it still wants to cover, is lowest-confidence, because the Agent SDK says newer models track multi-step work
without a written list; build it only if a matrix run shows coverage failing without it. SparkMe and SAGE-Agent are the references: code prices and ranks the open questions, the model chooses which to ask and how.

**8.3 Result strings: facts and options, imperatives only where money moves.** Keep the just-in-time channel, change the mood. Imperative stays where a wrong move loses money or trust and the case is unambiguous:
`BALANCE_PARTS` (a half-counted balance plans the month on half the person's money), `CONFIRM_AMOUNT` (a 12-rupee rent), `NO_ACTIONS` (inventing a shortfall that does not exist), `GOODBYE` and `UNDERSTOOD` (a silent
hang-up). Fact-plus-option replaces it elsewhere: `READ_BACK` keeps the read-back for exact money (Vapi's case) but drops the *"then ask"* clause; `CONFIRM_CHANGE` states both values (`rent: 11,000 -> 12,000`) and lets
the model judge, which it already does well and which had to be special-cased for balances; `READY_TO_PLAN` becomes a coverage fact (`nothing blocking; not yet discussed: other outgoings, other debts`), the change most
likely to fix "plans too early" and the one aligned with TIP
35. Rule of thumb for `CLAUDE.md`: *results state what happened and what is still open; they instruct only where a wrong move loses money.*

**8.4 Prompt: same length, different shape.** Do not shorten it, re-spend it: roughly 40% identity-as-behaviour, 25% goal and stance, 20% money and safety rules, 15% output format. Cut the conditionals, since every `If
X, do Y` whose case is knowable in code should become a fact in a result. Positive-frame the prohibitions: `Never invent, add, subtract, round or estimate` becomes `Every figure you say comes from a tool result, exactly
as written`. Replace the persona adjective with speech behaviour, per LiveKit: how this coach opens, reflects a figure back, recovers when it mishears. Add the stance: understand the month before proposing anything,
summarise what you heard and invite correction, ask leave before advising. Delete `Ask about missing fields in the given order` while keeping "one at a time", and the duplicate `never ask again about what you marked
unknown`, cut candidate C3.

**8.5 Evals, the load-bearing recommendation.** Add outcome checks alongside the 16 constraint checks, or none of the above survives contact with the matrix. `coverage_before_plan`: did the call establish the categories
that materially move the plan before `finalize_plan`? `explains_on_request`: when the sim user asks why, does the answer name components with every figure still traceable? `no_premature_plan`: MI's operational test, did
the plan arrive after the picture or on top of it? Replay each over `evals/runs` first, per the repo's own rule; `banned_phrases` and `no_markdown` are the checks most likely to be enforcing the form feel, so audit
whether each still catches a real defect. **What I would not do:** adopt Pipecat Flows or any node graph (Vapi is retiring theirs with a public reason, Retell compiles theirs back into a single prompt, LiveKit's four
split signals are absent here), shorten the prompt, or re-introduce code-side judgement, since the cut was right and 40 of 55 review findings sat in that machinery. The fix is not less structure or more; it is moving the
structure from imperatives-in-results to facts-in-results plus queries the model can ask.

## 9. What this changed

The redesign that came out of this report is `docs/process/agent-redesign-brief.md`. Four deltas from the recommendations above were applied to it:

1. **One question at a time is kept as a habit, the fixed order goes.** Three vendors recommend the one-question rule; none recommends a fixed order, and §8.1 shows the failing case only ever justified the former.
2. **The money rules are written as what to do, not what to avoid.** Per §1a and the Gemini over-indexing note, every prohibition in the money path is restated as the behaviour wanted.
3. **Imperatives survive only where money moves, and the coverage fact replaces the ready-to-plan nudge.** The `READY_TO_PLAN` instruction becomes a statement of what has and has not come up, per §8.3.
4. **Three outcome checks join the suite:** `no_premature_plan`, `explains_on_request`, `coverage_before_plan`, each replayed over `evals/runs` before it is trusted, per §8.5.
