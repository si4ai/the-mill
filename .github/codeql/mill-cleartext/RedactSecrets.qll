/**
 * Mill redaction entry points, used as sanitizers for the clear-text
 * logging and storage queries (card 1273).
 *
 * A path that never reaches one of these calls must still alert.
 */

import python
private import semmle.python.dataflow.new.DataFlow
private import semmle.python.ApiGraphs

/** Names of redaction helpers in agent_coord.server.redact. */
private string redactMember() {
  result =
    [
      "redact_secrets", "redact_text", "redact_format", "redact_obj", "err_text",
      "redact", "scrub_request_body"
    ]
}

/**
 * The result of a call to a mill redaction helper. In Python data flow the
 * call node is the returned value, so taint stops here and not at the
 * argument: a log of the unsanitized argument still alerts.
 */
class RedactSecretsResult extends DataFlow::Node {
  RedactSecretsResult() {
    exists(API::Node mod |
      mod =
        API::moduleImport("agent_coord.server.redact")
        or
        mod =
          API::moduleImport("agent_coord")
              .getMember("server")
              .getMember("redact")
    |
      this = mod.getMember(redactMember()).getACall()
    )
  }
}
