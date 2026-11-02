## What I Built
I built Prompt Lab, a single-file web app in plain HTML and JavaScript for testing prompts against Claude (claude-sonnet-5) through the Anthropic API. It runs by opening the file in a browser, with no server. It has a password-style API key field that never saves the key, an optional system prompt, a labeled conversation log that shows exactly what Claude sees, a New Conversation button, and an Export button that saves a run as Markdown. I used it for four runs on business tasks for a fictional company, Wildframe Coffee Roasters: brainstorming loyalty perks, writing bean cards, replying to customer comments, and choosing a pop-up stand location. Each run tested a different prompting technique.

## Why This Approach
Task 1 - Technique: zero-shot
Brainstorming loyalty perks is an open-ended creative task, so I gave no examples: an example perk would have anchored Claude toward ideas like it and cut the variety I wanted. Instead, I described the brand, the customers, and the goal, and controlled the output with explicit constraints: exactly 6 ideas, one sentence each of at most 25 words, at most one straight discount, and no "exclusive" or "VIP."

Task 2 - Technique: one-shot
The bean cards had to follow a fixed five-line layout with exact labels, order, and capitalization, which is much easier to show than to describe. One finished card (Huila, Colombia) showed the format and the tone of the "Real talk" line at once. One example was enough because the format is the same for every card, and only the coffee details change, which I supplied.

Task 3 - Technique: few-shot
Brand voice is hard to define in words, so I gave four real comment-and-reply pairs instead of one. Each example covered a different situation (a skeptical question, a complaint, praise, and a how-to question), so Claude could pick up the voice across situations rather than copy a single reply. That mattered because the three new comments were also different kinds: a late order, a product question, and a thank-you.

Task 4 - Technique: chain-of-thought
Choosing a pop-up location means doing arithmetic on several figures, checking a hard budget limit, and then weighing money against fit with the brand. Asking Claude to work through numbered steps and show its arithmetic made it calculate before recommending, so the recommendation follows from the numbers instead of a first impression. It also made the reasoning checkable: I could confirm each number, and that Union Station's $8,000 four-week rent breaks the $5,000 budget.

## Example Run
Model: claude-sonnet-5

### You

You are the community manager for Wildframe Coffee Roasters, a specialty coffee roaster that sells beans online and through a monthly subscription. Our customers are environmentally conscious urban professionals.

Here are four customer comments with the replies we posted. They show our voice:

Comment: Is your packaging actually recyclable, or is that just marketing?
Reply: Fair question. The bag is compostable, the little valve isn't, so pop the valve off first. We're working on that last bit.

Comment: Your Kenya roast tasted burnt to me.
Reply: That's not the cup we were going for. Tell us how you brewed it and we'll help you dial it in, or swap you to something mellower.

Comment: Best coffee I've had in years!!
Reply: This made our whole roasting crew's morning. We'll keep doing the thing.

Comment: Can I pause my subscription while I travel?
Reply: Yep. Account, then Subscription, then Pause. Your beans will wait for you, mostly patiently.

Reply to these three new comments in this same voice:
1. My order was supposed to arrive Monday. It's Thursday.
2. Do you make any decaf that doesn't taste like cardboard?
3. The Huila is my new Sunday morning ritual. Thank you.

Return three replies numbered 1 to 3, each no more than 40 words, with no emoji, hashtags, exclamation points, or corporate jargon. Don't copy phrases from the example replies. Don't invent facts you weren't given, such as an order's status, delivery dates, refunds, or which decaf coffees we sell; where a reply needs that information, invite the customer to message us so we can look into it.

### Claude

1. Four days late isn't the kind of patience we meant. Send us your order number and we'll find out what happened and get it sorted.

2. We'd like to think so. Tell us what you usually brew and we'll point you toward a decaf that fits, no cardboard guaranteed.

3. Huila on a Sunday sounds like a solid ritual. Glad it's found a place in your week.

## Reflection
Across the four tasks, the technique that made the biggest difference was the one-shot example in Task 2. Claude matched the five-line layout exactly for all three cards and added no facts, which would have been hard to guarantee with a description alone. The chain-of-thought prompt in Task 4 also worked well: every calculation was correct, and the required budget check ruled out Union Station before profit was considered. It did slip in assumptions without labeling them, such as library visitors being students, even though I asked for assumptions to be stated. The zero-shot prompt in Task 1 met every constraint, though two ideas overlapped on "small-batch" and the free bag in idea 2 is close to a second discount.

The choice I'm least sure of is few-shot for Task 3. The voice was right, but reply 1 echoed "mostly patiently" from my examples despite my recomendation not to copy them. Four examples may have pulled Claude toward reusing wording. Next time I would try two or three more varied examples, or move the voice examples into the system prompt and add an instruction to double-check any dates or numbers before replying.
