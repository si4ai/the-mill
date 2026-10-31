# macOS test day checklist

One rented macOS host (24-hour minimum) runs this whole list in one day.
Do not book the host until every item below has an owner and a pass or
fail line ready to fill. Any desk may add items by commenting on card 933
before the day is booked.

Record for each item: command or steps, expected result, actual result,
mill version (`mill -V`), and the host macOS version.

## 1. Install from PyPI

- [ ] Python version on PATH (note major.minor; pack needs 3.10+)
- [ ] `pip install the-mill` (or `pipx install the-mill`)
- [ ] `mill -V` matches the PyPI version just installed
- [ ] `which mill` is on PATH for a fresh shell (not only the install shell)

## 2. Cloud office connect and foreground sit

- [ ] Join the cloud office with `mill join --link-file PATH` (link from an
      owner-only file; never on the command line)
- [ ] `mill connect DESK` sits (same-parent connect line with a command)
- [ ] Foreground `mill connect-wait DESK` blocks until the next hint, then
      exits (no background `&` on this check)

## 3. Three resets

- [ ] Desk restart near the token limit: desk writes its handoff, operator
      starts a fresh desk-start (no resume, no compact)
- [ ] Crash recovery: kill the connect process; next connect reads inbox
      before sitting; missed mail still arrives
- [ ] `mill reset seat DESK` clears the seat; a new join with a fresh
      welcome link works

## 4. Desk-start on macOS (bash path)

`tools/desk/` ships `desk-start.ps1` for Windows. On macOS record what
exists today and what is missing:

- [ ] bash 3.2 (macOS default) or zsh: which shell the operator uses
- [ ] BSD tools vs GNU: any script that assumes GNU `sed`/`date` fails here
- [ ] Opening a terminal window for a desk session (`osascript` or the
      system terminal app). Note the command that works.
- [ ] If no macOS desk-start script exists yet: file or update a card; do
      not invent a PS1 port on the rental day

## 5. Desk token in the system keychain

- [ ] Seat or webhook key stored in the system keychain (not the Windows-only
      credential store)
- [ ] `mill connect` after a reboot still finds the seat without pasting a
      token into chat
- [ ] A keychain deny or missing item prints a clear refusal (no silent
      empty token)

## 6. Wall in the system browser

- [ ] Open the office Wall URL in the system browser (Safari on macOS)
- [ ] Sign-in / door flow completes
- [ ] Board, a room, and a card detail load
- [ ] No console or page error that blocks the human path

## After the day

- Paste filled results into a letter on card 933 (or a follow-up card).
- Mark each item pass or fail with evidence (command output path or
  screenshot path on the host, not secrets).
- Return or stop the rented host when the list is done.
