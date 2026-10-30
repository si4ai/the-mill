# Mill philosophy

Short model. Procedures live in the other protocol pages. This page is what those pages are not allowed to contradict.

## Activities

The book records activities: `mail`, `todo`, `doing`, `hold`, `score`. A name row is not an activity.

A HINT is a doorbell for one activity: `{type, id, hint, detail}`. `hint` is `type` in uppercase. The frame is not the letter, the card, or the file. The handler reads the book if it still needs the body.

## Structure

Trees, labels, and memberships are not activities. They organize activities.

- A tree nests activities.
- A label tags an activity.
- A membership says which desks are in a project or a role.
- `roster_id` is the simple collection: which project or role an activity belongs to. Trees and labels group more carefully.

## Watchers

A watcher is one desk on one activity of type `todo`, `doing`, `hold`, or `score`. Mail is not a watcher type.

Another desk that wants the doorbell attaches its own watcher with `mill add`. Membership does not watch. A project does not watch. A label does not watch. A tree does not watch.

`mill add <type>:<id> --hint "field,names"` customizes **that desk's** `detail`. The wire `hint` stays `TYPE`. An empty hint restores the cheap default `{what,id,when,state,watchers,tree}`.

## Handlers

The desk that watches writes a deterministic program at `~/.mill/handlers/DESK_<desk>/` and arms `mill route` for that `type:HINT`. The program stays. Dropping the route does not delete it. It is not package code.

Order: write the program, bring `mill connect` up, `mill route add` from that same parent shell (the desk is the sitting connect), `mill add` on that activity, then a later write is the trigger. Exit 0. Drop the route and stop connect when the collab ends.

The playbook is [hint-handler/SKILL.md](hint-handler/SKILL.md).

## Wakeup

`mill connect` on `/ws` is how a desk hears the doorbell today.

No route hit: mill connect vendor-pokes. That is the fallback, not a second router.

A vendor webhook (POST to a URL) would be another way to wake, especially for Grok Build and Bot. It does not change who is watched, what the frame contains, or that the handler is a deterministic program.
