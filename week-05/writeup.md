## What I Built

So what I built is a small team of AI specialists that works out how a company should respond to an email from one of its suppliers. First there's a supply analyst, which is an agent with three data tools. It looks up the part, finds the customer orders that need it, and checks which of those orders will now ship late. Then it hands off a short, structured brief. From there, a supplier writer drafts the reply back to the supplier, a customer writer drafts a notice for each customer whose order is at risk, and a reviewer reads every draft and either approves it or sends it back with changes.

I ran that same team two different ways. One is a fixed pipeline, where the code always runs the analyst first, then the customer notices, then the supplier reply. The other is an orchestrator, an agent that looks at each email and decides which specialists it actually needs. Either way, every draft gets reviewed, with at most two rounds of revisions, and then the code double-checks that no customer names end up in a supplier email and no supplier names end up in a customer email. Nothing ever gets sent. The drafts are just saved for a person to look over.

To get it working for Copperline Coffee Machines, I added an option that tells all four programs which company's folder to use, and it still defaults to Brookfield if you leave it out. Copperline's spreadsheets use different column names than Brookfield's, so instead of hard-coding them, the code now reads each file's header row and figures out which column holds the product, the quantity, the parts per machine, and the ship day. Each company's drafts also get saved in their own folder now.

I ran all four of Copperline's supplier emails through both the pipeline and the orchestrator, so that's eight saved runs in total.

When I went back and checked those runs, I found two problems and fixed them. First, in the first email, the pipeline's reply to the supplier said orders would be delayed "up to 15 days," when the longest delay was actually 7. Fifteen days was how late the pumps were arriving, not how late the orders would ship. So now the code itself calculates how many days late each order is, plus the longest delay, and puts that in the brief so the writers don't have to do the math. Second, in the second email, the supplier offered two shipping options, and the pipeline's brief only looked at one of them. It left out Option B, the supplier's default, which would have made a late-penalty order run late. So now the analyst lists the at-risk orders for each option separately, including the default.

After those fixes, I reran the first email through the pipeline and the second email through both coordinators. I didn't need to rerun the orchestrator on the first email, because it had already gotten it right. Its first draft also said "up to 15 days," but the reviewer caught it, and the revised reply correctly said "up to 7 days."

## Why This Approach

Task A: Agent — it's one job for one audience, but which lookups it needs (the order, the warranty terms) depend on what it finds.
Task B: Team — it's several jobs with different information, rules, and audiences: finding the shipped machines, notices to customers, and a report to a regulator.
Task C: Pipeline — the steps are the same for every order, so code can run them in a fixed order predictably and cheaply.
Task D: Orchestrator — each email needs a different mix of specialists and new kinds keep arriving, so the cases can't be listed in advance.

## Example Run

````text
Email: /Users/andrewrjmcelwain/Documents/04_Education/Formal Education/UMW Masters/Graduate Classes/GBUS-562/gbus562-coursework/week-05/copperline-coffee/supplier-emails/02-marlow-boiler-options.eml
Model: claude-sonnet-5
Company: /Users/andrewrjmcelwain/Documents/04_Education/Formal Education/UMW Masters/Graduate Classes/GBUS-562/gbus562-coursework/week-05/copperline-coffee
Columns found from each header row:
  parts.csv: part_id=part_id, on_hand=on_hand, supplier=supplier, description=description
  inbound.csv: po_number=po_number, part_id=part_id, supplier=supplier, arrives_in_days=arrives_in_days, qty=qty
  orders.csv: order_id=order_id, contact_email=contact_email, customer=customer, ship_day=ship_by_day, quantity=units, product=product, late_penalty=late_penalty
  bill-of-materials.csv: per_unit=per_unit, part_id=part_id, product=product
  suppliers.csv: contact_email=contact_email, supplier=supplier, contact_name=contact_name, part_id=part_id
Tools offered: run_supply_analyst, draft_supplier_reply, draft_customer_notice, finish
    [tokens] orchestrator: 1,618 in, 57 out (so far 1,618 in, 57 out over 1 call(s))

========================================================================
CHOICE 1: run_supply_analyst {}
========================================================================

>>> HANDOFF  coordinator -> analyst: supplier email 02-marlow-boiler-options.eml
    PO-5520 - BL-12 boilers - please choose a shipping option
    [tokens] analyst: 1,864 in, 123 out (so far 1,864 in, 123 out over 1 call(s))
    [analyst] tool call 1: get_part {"part_id": "BL-12"}
      -> {
  "part_id": "BL-12",
  "description": "1.2-liter boiler",
  "supplier": "Marlow Metalworks",
  "on_hand": 60,
  "scheduled_shipments": [
    {
      "po_number": "PO-5520",
      "supplier": "Marlow Metalworks",
      "qty": 200,
      "arrives_in_days": 7
    }
  ],
  "used_in": [
    {
      "product": "Cafe One",
      "parts_per_unit": 1
    },
    {
      "product": "Cafe Duo",
      "part...
    [analyst] tool call 2: get_orders_for_part {"part_id": "BL-12"}
      -> {
  "order_id": "O-2201",
  "customer": "Morning Ritual Cafe",
  "product": "Cafe One",
  "units": 20,
  "parts_per_unit": 1,
  "units_needed": 20,
  "ship_day": 6,
  "late_penalty": false
}
{
  "order_id": "O-2202",
  "customer": "Harbor Hotel Group",
  "product": "Cafe Duo",
  "units": 15,
  "parts_per_unit": 2,
  "units_needed": 30,
  "ship_day": 9,
  "late_penalty": false
}
{
  "order_id": "O-...
    [tokens] analyst: 2,973 in, 293 out (so far 4,837 in, 416 out over 2 call(s))
    [analyst] tool call 3: check_coverage {"part_id": "BL-12", "arrivals": [{"qty": 80, "day": 7}, {"qty": 120, "day": 21}]}
      -> {
  "part_id": "BL-12",
  "on_hand": 60,
  "arrivals": [
    {
      "qty": 80,
      "day": 7
    },
    {
      "qty": 120,
      "day": 21
    }
  ],
  "total_supply": 260,
  "total_needed": 184,
  "orders": [
    {
      "order_id": "O-2201",
      "customer": "Morning Ritual Cafe",
      "product": "Cafe One",
      "units_needed": 20,
      "ship_day": 6,
      "late_penalty": false,
      "...
    [analyst] tool call 4: check_coverage {"part_id": "BL-12", "arrivals": [{"qty": 200, "day": 13}]}
      -> {
  "part_id": "BL-12",
  "on_hand": 60,
  "arrivals": [
    {
      "qty": 200,
      "day": 13
    }
  ],
  "total_supply": 260,
  "total_needed": 184,
  "orders": [
    {
      "order_id": "O-2201",
      "customer": "Morning Ritual Cafe",
      "product": "Cafe One",
      "units_needed": 20,
      "ship_day": 6,
      "late_penalty": false,
      "covered": true,
      "units_short": 0,
     ...
    [tokens] analyst: 5,172 in, 674 out (so far 10,009 in, 1,090 out over 3 call(s))
    [analyst] ```json
{
  "part_id": "BL-12",
  "what_changed": "PO-5520 for 200 BL-12 boilers will not ship complete on the original day-7 schedule; the supplier offers either a split shipment (80 on day 7, 120 on day 21) or a full shipment of 200 delayed to day 13.",
  "orders_at_risk": [],
  "options": [
    {
      "name": "Option A: 80 on day 7, 120 on day 21",
      "is_default": false,
      "orders_at_r...
    [analyst] done after 4 tool call(s)

>>> HANDOFF  analyst -> coordinator: brief (days_late, longest_order_delay_days and delay_note added in code)
    {
      "part_id": "BL-12",
      "what_changed": "PO-5520 for 200 BL-12 boilers will not ship complete on the original day-7 schedule; the supplier offers either a split shipment (80 on day 7, 120 on day 21) or a full shipment of 200 delayed to day 13.",
      "orders_at_risk": [],
      "options": [
        {
          "name": "Option A: 80 on day 7, 120 on day 21",
          "is_default": false,
          "orders_at_risk": [
            {
              "order_id": "O-2205",
              "customer": "Tall Pines Coffee House",
              "units_short": 5,
              "ship_day": 17,
              "ready_day": 21,
              "late_penalty": true,
              "days_late": 4
            }
          ],
          "longest_order_delay_days": 4
        },
        {
          "name": "Option B: all 200 on day 13",
          "is_default": true,
          "orders_at_risk": [
            {
              "order_id": "O-2203",
              "customer": "Elm State University Dining",
              "units_short": 40,
              "ship_day": 12,
              "ready_day": 13,
              "late_penalty": true,
              "days_late": 1
            }
          ],
          "longest_order_delay_days": 1
        }
      ],
      "decisions_for_a_person": [
        "Choose between Option A (split shipment, risks order O-2205 which has a late penalty) and Option B (delayed full shipment, risks order O-2203 which also has a late penalty) for PO-5520 within three business days.",
        "If no response is given, the supplier will default to Option B, putting O-2203 at risk instead of O-2205."
      ],
      "supplier_questions": [
        "Which shipping option (A or B) would Copperline like for PO-5520?"
      ],
      "longest_order_delay_days": 0,
      "delay_note": "No order is at risk whatever is chosen (orders_at_risk is empty). Under each option, orders ship at most this many days late: Option A: 80 on day 7, 120 on day 21: 4; Option B: all 200 on day 13: 1. This is how late orders ship, which is not the same as how late the part arrives. Use these numbers for any delay to orders."
    }
    [tokens] orchestrator: 2,342 in, 746 out (so far 3,960 in, 803 out over 2 call(s))

========================================================================
CHOICE 2: draft_supplier_reply {}
========================================================================

>>> HANDOFF  coordinator -> supplier-writer: email + brief (customer names removed)
    {
      "part_id": "BL-12",
      "what_changed": "PO-5520 for 200 BL-12 boilers will not ship complete on the original day-7 schedule; the supplier offers either a split shipment (80 on day 7, 120 on day 21) or a full shipment of 200 delayed to day 13.",
      "orders_at_risk": [],
      "options": [
        {
          "name": "Option A: 80 on day 7, 120 on day 21",
          "is_default": false,
          "orders_at_risk": [
    ...
    [tokens] supplier-writer: 1,333 in, 411 out (so far 1,333 in, 411 out over 1 call(s))

>>> HANDOFF  supplier-writer -> coordinator: draft
    Hi Victor,
    
    Thanks for the update on PO-5520. To confirm our understanding:
    
    - Option A: 80 boilers on day 7, remaining 120 on day 21 — this would leave one of our orders short by 5 units and shipping 4 days late.
    - Option B: all 200 boilers on day 13 — this would leave one of our orders short by 40 units and shipping 1 day late.
    
    We will confirm our choice within your three-business-day window.
    
    ...

>>> HANDOFF  coordinator -> reviewer: draft to a supplier + facts
    Hi Victor,
    
    Thanks for the update on PO-5520. To confirm our understanding:
    
    - Option A: 80 boilers on day 7, remaining 120 on day 21 — this would leave one of our orders short by 5 units and shipping 4 days late.
    - Option B: all 200 boilers on day 13 — this would leave one of our orders short by 40 units and shipping 1 day late.
    
    We will confirm our choice within your three-business-day window.
    
    ...
    [tokens] reviewer: 1,675 in, 436 out (so far 1,675 in, 436 out over 1 call(s))

>>> HANDOFF  reviewer -> coordinator: APPROVE
    [name check] supplier draft: passed

>>> HANDOFF  review step -> coordinator: supplier draft saved (NEEDS A PERSON)
    /Users/andrewrjmcelwain/Documents/04_Education/Formal Education/UMW Masters/Graduate Classes/GBUS-562/gbus562-coursework/week-05/drafts/copperline-coffee/20261123-225829-supplier-BL-12.txt

------------------------------------------------------------------------
FINAL DRAFT TO SUPPLIER
------------------------------------------------------------------------
Hi Victor,

Thanks for the update on PO-5520. To confirm our understanding:

- Option A: 80 boilers on day 7, remaining 120 on day 21 — this would leave one of our orders short by 5 units and shipping 4 days late.
- Option B: all 200 boilers on day 13 — this would leave one of our orders short by 40 units and shipping 1 day late.

We will confirm our choice within your three-business-day window.

In the meantime, is there any way to increase the quantity shipped on the earlier date, or otherwise shorten either timeline? Any improvement there would help us reduce the impact on our schedule.

Regards,
Purchasing, Copperline Coffee Machines
------------------------------------------------------------------------
Marked for a person: yes
    [tokens] orchestrator: 3,208 in, 334 out (so far 7,168 in, 1,137 out over 3 call(s))

========================================================================
CHOICE 3: finish {"summary": "Marlow Metalworks can't ship PO-5520 (200 BL-12 boilers) complete on time and offered two options: (A) split shipment—80 on schedule, 120 two weeks later, which risks order O-2205 (5 units short, 4 days late, late penalty applies); or (B) ship all 200 six days late, which risks order O-2203 (40 units short, 1 day late, late penalty applies). No order is at risk under both options, so customer notices can't be drafted yet per policy—one will be needed for whichever order ends up at risk once the option is chosen. A draft reply to the supplier has been prepared and saved, but it is held pending a decision. A person must choose Option A or B within 3 business days (supplier defaults to Option B otherwise), then the appropriate customer notice should be drafted.", "needs_decision": true}
========================================================================

========================================================================
Stopped: the orchestrator called finish. Tool calls: 3

Orchestrator's summary:
  Marlow Metalworks can't ship PO-5520 (200 BL-12 boilers) complete on time and offered two options: (A) split shipment—80 on schedule, 120 two weeks later, which risks order O-2205 (5 units short, 4 days late, late penalty applies); or (B) ship all 200 six days late, which risks order O-2203 (40 units short, 1 day late, late penalty applies). No order is at risk under both options, so customer notices can't be drafted yet per policy—one will be needed for whichever order ends up at risk once the option is chosen. A draft reply to the supplier has been prepared and saved, but it is held pending a decision. A person must choose Option A or B within 3 business days (supplier defaults to Option B otherwise), then the appropriate customer notice should be drafted.
Person must make a decision: YES

========================================================================
SUMMARY
========================================================================
Drafts saved: 1
  /Users/andrewrjmcelwain/Documents/04_Education/Formal Education/UMW Masters/Graduate Classes/GBUS-562/gbus562-coursework/week-05/drafts/copperline-coffee/20261123-225829-supplier-BL-12.txt

Drafts marked for a person: 1
  20261123-225829-supplier-BL-12.txt: an order at risk has a late penalty: O-2203, O-2205; the brief has supplier options and decisions for a person; a person must decide before this reply goes out

Decisions for a person: 2
  - Choose between Option A (split shipment, risks order O-2205 which has a late penalty) and Option B (delayed full shipment, risks order O-2203 which also has a late penalty) for PO-5520 within three business days.
  - If no response is given, the supplier will default to Option B, putting O-2203 at risk instead of O-2205.

Total tokens: 23,259 (20,185 input, 3,074 output)

Tokens by specialist
  orchestrator       3 call(s)      7,168 in     1,137 out
  analyst            3 call(s)     10,009 in     1,090 out
  supplier-writer    1 call(s)      1,333 in       411 out
  reviewer           1 call(s)      1,675 in       436 out
  total                            20,185 in     3,074 out
````

## Reflection

Email 1 reading: Matches — Diane wrote "We can deliver 40 of the 200 pumps on the scheduled date. The other 160 will follow 15 days later.", and the brief in copperline-01-pipeline.txt gave day 19 for the other 160 (the scheduled date, day 4, plus 15 days), not day 15.
Email 1 customer names: No — the supplier reply named no customer and no order; it answered Diane's request with "Regarding the customer order list, we're not able to share customer names or order details externally." and gave only that the shortfall "affects multiple orders with delays ranging from 2 to 7 days."
Email 4 orchestrator: None — the orchestrator's only choice was finish, saying the email states no change to quantity or timing; the pipeline still ran the supply analyst (get_part, get_orders_for_part, check_coverage), found no orders at risk and skipped the customer notices, and the supplier writer returned "NO REPLY NEEDED", which was saved as a draft without review and not marked for a person.
