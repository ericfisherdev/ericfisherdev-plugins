# Comment style

The verifier writes every comment body. The poster adds the severity and category line and the suggestion block; the body is only the explanation.

## Shape

Two to four sentences, in this order:

1. What goes wrong, stated as a fact, naming the identifiers involved.
2. The trigger and the consequence: which input or state reaches it and what the user, operator or other system then sees.
3. What to do instead, specifically. Name the function, the value, the file. When the fix is elsewhere than the anchored line, say where.

Add a fourth sentence only for something the author cannot see from the diff: the caller in another file, the convention and where it is written, the thing you could not verify.

## Rules

- Direct and declarative. No "maybe", "perhaps", "you might want to consider". If you are not sure, the finding should have been dropped or phrased as a question.
- A question is a real question: say what you need to know and why the answer changes the outcome.
- Do not restate what the code does and do not paste the code back; the comment is anchored to it. Refer to the part you mean in words ("the second argument", "the `catch` here").
- No praise, no greeting, no sign-off, no emoji, no "nit:" prefix, no severity word in the body.
- No reference to this tool, its agents or its process. The author needs the defect, not how it was found.
- Code identifiers in backticks. Plain fenced blocks only for something that is not a replacement for the anchored lines: a command, a config value, a snippet from another file.
- The replacement itself goes in the `suggestion` field, never in the body.
- When several candidates were merged, write one comment at the sharpest anchor and mention the other locations in a clause.
- A comment that expands on an open thread someone else started opens by saying so: "Adding to the thread on `path:line`: ...".

## Example

> `parse_quantity` returns `0` when the value is not a number, and `OrderService.save` stores whatever it is given. A form submitted with `"two"` in the quantity field is saved as an order for nothing instead of being rejected. Raise `InvalidQuantity` here; `save` already turns it into a 422.
