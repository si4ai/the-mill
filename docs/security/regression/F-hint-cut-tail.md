# F-hint-cut-tail

card 902. When a mail HINT or lean inbox row cuts the body, the text ends with
a visible ASCII tail `... [cut: N more chars, mill mail-thread ID]` (tail counts
inside the cap). reason=addressed live wakes carry the whole letter up to
LETTER_CAP (4096). reason=room wakes and connect replay / default keep BODY_CAP
(1024) plus the tail. Uncut bodies unchanged. Fields body_trunc, body_chars,
and read stay set when cut.
